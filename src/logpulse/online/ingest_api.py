"""Ingest API + dashboard API (notes 02 and 13).

    POST /ingest                  Fluent Bit http output (JSON array of records)
    GET  /api/status | services | stream | traces | traces/{id} | alerts | templates
         transitions | scoreboard | runs | faults
    POST /api/faults/{id} | /api/faults/restore      proxied to the chaos service
    POST /api/ground_truth                            written by the injector only
    POST /api/feedback                                "mark false alarm"
    POST /api/admin/reset                             start a new run (new SQLite file)
    GET  /ui                                          React topology / flow-graph page

Every GET accepts ?run=<name> to replay a recorded run from its SQLite file.

    uvicorn logpulse.online.ingest_api:app --port 9000
"""
from __future__ import annotations

import json
import os
import threading
import time
import traceback
from pathlib import Path

import httpx
import pandas as pd
import torch
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from logpulse import store
from logpulse.eval import live
from logpulse.online.detector import BASELINES, MODEL_DETECTORS, Pipeline
from logpulse.paths import ARTIFACTS, LIVE_RUNS, ROOT, RUNS

ART_DIR = Path(os.environ.get("LOGPULSE_ARTIFACTS", ARTIFACTS / "demo"))
CHAOS_URL = os.environ.get("CHAOS_URL", "http://localhost:9100")
SERVICE_URLS = dict(kv.split("=", 1) for kv in os.environ.get(
    "SERVICE_URLS", "gateway=http://localhost:8000").split(",") if "=" in kv)
TOPOLOGY = {
    "nodes": ["gateway", "orders", "inventory", "payment", "db", "fluent-bit"],
    "edges": [["gateway", "orders"], ["orders", "inventory"], ["orders", "payment"], ["inventory", "db"]],
    "infra": ["db", "fluent-bit"],
}
PRIMARY = "deeplog_full"
DETECTORS = MODEL_DETECTORS + BASELINES

torch.set_num_threads(int(os.environ.get("TORCH_THREADS", "2")))
app = FastAPI(title="LogPulse detector")
state: dict = {"pipeline": None, "stop": threading.Event(), "errors": 0}


def start(run: str, mode: str):
    old = state.get("pipeline")
    if old is not None:
        old.close(export_to=RUNS / f"{old.run}.db")
    state["pipeline"] = Pipeline(LIVE_RUNS / f"{run}.db", ART_DIR, mode=mode, run=run, service_urls=SERVICE_URLS)
    print(f"[detector] run={run} mode={mode} model={state['pipeline'].version}", flush=True)


def _loop():
    while not state["stop"].is_set():
        p = state["pipeline"]
        try:
            if p is not None:
                p.tick()
        except Exception:  # keep ingesting even if one batch is bad
            state["errors"] += 1
            traceback.print_exc()
        time.sleep(0.25)


def _health_loop():
    while not state["stop"].is_set():
        p = state["pipeline"]
        interval = p.cfg["b3_interval"] if p else 10.0
        try:
            if p is not None and p.service_urls:
                p.probe_health()
        except Exception:
            traceback.print_exc()
        time.sleep(interval)


@app.on_event("startup")
def _startup():
    run = os.environ.get("LOGPULSE_RUN", "default")
    mode = os.environ.get("LOGPULSE_MODE", "detect" if (ART_DIR / "deeplog.pt").exists() else "collect")
    start(run, mode)
    threading.Thread(target=_loop, daemon=True).start()
    threading.Thread(target=_health_loop, daemon=True).start()


# ------------------------------------------------------------------ ingest
@app.post("/ingest")
async def ingest(request: Request):
    body = await request.json()
    state["pipeline"].submit(body)
    return {"ok": True}


# ------------------------------------------------------------------ helpers
def _con(run: str | None):
    p = state["pipeline"]
    if run is None or (p is not None and run == p.run):
        if p is None:
            raise HTTPException(503, "pipeline not started")
        return store.connect(p.db_path, readonly=True), p, False
    path = LIVE_RUNS / f"{run}.db"
    if not path.exists():
        path = RUNS / f"{run}.db"
    if not path.exists():
        raise HTTPException(404, f"no run {run}")
    return store.connect(path, readonly=True), None, True


def _now(con, replay: bool) -> float:
    if not replay:
        return time.time()
    return con.execute("SELECT MAX(received_at) FROM raw_lines").fetchone()[0] or time.time()


def _rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


# ------------------------------------------------------------------ read API
@app.get("/api/status")
def status(run: str | None = None):
    con, p, replay = _con(run)
    info = store.get_info(con)
    n = con.execute("SELECT COUNT(*) FROM raw_lines").fetchone()[0]
    out = {"run": info.get("run"), "mode": info.get("mode"), "version": info.get("version"), "cfg": info.get("cfg"),
           "lines": n, "replay": replay, "errors": state["errors"]}
    if p is not None:
        out["stats"] = p.stats
    con.close()
    return out


@app.get("/api/services")
def services(run: str | None = None, detector: str = PRIMARY):
    con, p, replay = _con(run)
    now = _now(con, replay)
    lps = dict(con.execute("SELECT service, COUNT(*) / 10.0 FROM raw_lines WHERE received_at > ? GROUP BY service",
                           (now - 10,)).fetchall())
    anom = dict(con.execute("SELECT service, COUNT(DISTINCT trace_id) FROM alerts WHERE detector = ? AND ts > ? "
                            "GROUP BY service", (detector, now - 60)).fetchall())
    recent = dict(con.execute("SELECT service, COUNT(DISTINCT trace_id) FROM alerts WHERE detector = ? AND ts > ? "
                              "GROUP BY service", (detector, now - 30)).fetchall())
    traces = dict(con.execute("SELECT service, COUNT(DISTINCT trace_id) / 10.0 FROM events WHERE ts > ? "
                              "GROUP BY service", (now - 12,)).fetchall())
    health = dict(p.b3_state) if p is not None else {}
    nodes = []
    for s in TOPOLOGY["nodes"]:
        r = recent.get(s, 0)
        color = "grey" if s in TOPOLOGY["infra"] else ("red" if r >= 3 or health.get(s) == "down"
                                                         else "amber" if r >= 1 else "green")
        nodes.append({"id": s, "lines_per_s": round(lps.get(s, 0.0), 1), "anomalous_per_min": anom.get(s, 0),
                      "health": health.get(s, "?"), "color": color, "infra": s in TOPOLOGY["infra"]})
    edges = [{"source": a, "target": b, "req_per_s": round(traces.get(b, 0.0), 1) if b != "db" else None,
              "anomalous": recent.get(b, 0) > 0} for a, b in TOPOLOGY["edges"]]
    con.close()
    return {"nodes": nodes, "edges": edges, "now": now}


@app.get("/api/stream")
def stream(since: int = 0, limit: int = 200, run: str | None = None):
    con, _, _ = _con(run)
    rows = _rows(con.execute(
        "SELECT r.id, r.ts, r.container, r.service, r.level, r.trace_id, r.msg, e.event_id, e.template, e.unseen, "
        "e.matched_to FROM raw_lines r JOIN events e ON e.raw_id = r.id WHERE r.id > ? ORDER BY r.id DESC LIMIT ?",
        (since, limit)))
    n_min = con.execute("SELECT COUNT(*), COUNT(DISTINCT e.event_id) FROM raw_lines r JOIN events e "
                        "ON e.raw_id = r.id WHERE r.received_at > ?", (_now(con, run is not None) - 60,)).fetchone()
    con.close()
    return {"lines": rows[::-1], "lines_last_min": n_min[0], "distinct_events_last_min": n_min[1]}


@app.get("/api/traces")
def recent_traces(seconds: float = 30, limit: int = 30, run: str | None = None):
    con, _, replay = _con(run)
    now = _now(con, replay)
    ev = pd.read_sql_query("SELECT trace_id, ts, service, event_id FROM events WHERE ts > ? AND trace_id != '-' "
                           "ORDER BY ts", con, params=(now - seconds,))
    al = pd.read_sql_query("SELECT trace_id, detector, step FROM alerts WHERE ts > ? AND trace_id IS NOT NULL",
                           con, params=(now - seconds - 30,))
    con.close()
    out = []
    for tid, g in list(ev.groupby("trace_id", sort=False))[-limit:]:
        a = al[(al["trace_id"] == tid) & (al["detector"] == PRIMARY)]
        out.append({"trace_id": tid, "events": g["event_id"].tolist(), "services": g["service"].tolist(),
                    "start_ts": float(g["ts"].iloc[0]), "anomalous": bool(len(a)),
                    "bad_step": int(a["step"].iloc[0]) if len(a) and pd.notna(a["step"].iloc[0]) else None})
    interleaved = ev.tail(60)[["trace_id", "event_id", "service"]].to_dict("records")
    return {"traces": out, "interleaved": interleaved}


@app.get("/api/traces/{trace_id}")
def trace(trace_id: str, run: str | None = None):
    con, _, _ = _con(run)
    events = _rows(con.execute("SELECT e.*, r.container, r.capture_file, r.line_no, r.msg FROM events e "
                               "JOIN raw_lines r ON r.id = e.raw_id WHERE e.trace_id = ? ORDER BY e.ts, e.id",
                               (trace_id,)))
    decisions = _rows(con.execute("SELECT * FROM decisions WHERE trace_id = ? ORDER BY step", (trace_id,)))
    alerts = pd.read_sql_query("SELECT * FROM alerts WHERE trace_id = ? ORDER BY ts", con, params=(trace_id,))
    session = con.execute("SELECT * FROM sessions WHERE trace_id = ?", (trace_id,)).fetchone()
    gt = pd.read_sql_query("SELECT * FROM ground_truth", con)
    sess = pd.read_sql_query("SELECT * FROM sessions WHERE trace_id = ?", con, params=(trace_id,))
    con.close()
    mapped = live.map_alerts(alerts, gt, sess)
    verdicts = []
    for r in mapped.itertuples():
        verdicts.append({"alert_id": r.id, "detector": r.detector,
                         "verdict": "TRUE POSITIVE" if r.fault_id else ("in fault window, other service"
                                                                        if r.in_fault_window else "FALSE POSITIVE"),
                         "fault_id": r.fault_id})
    alerts_out = json.loads(alerts.to_json(orient="records")) if len(alerts) else []
    return {"trace_id": trace_id, "events": events, "decisions": decisions, "alerts": alerts_out,
            "verdicts": verdicts, "session": dict(session) if session else None}


@app.get("/api/alerts")
def alerts(limit: int = 50, detector: str | None = None, run: str | None = None):
    con, _, _ = _con(run)
    q = "SELECT * FROM alerts" + (" WHERE detector = ?" if detector else "") + " ORDER BY ts DESC LIMIT ?"
    a = pd.read_sql_query(q, con, params=(detector, limit) if detector else (limit,))
    gt = pd.read_sql_query("SELECT * FROM ground_truth", con)
    tids = [t for t in a["trace_id"].dropna().unique()]
    sess = pd.read_sql_query(f"SELECT * FROM sessions WHERE trace_id IN ({','.join('?' * len(tids))})", con,
                             params=tids) if tids else pd.DataFrame(columns=["trace_id", "services", "called"])
    con.close()
    m = live.map_alerts(a, gt, sess)
    gt_by_id = gt.set_index("fault_id").to_dict("index") if len(gt) else {}
    m["verdict"] = ["TP" if f else ("?" if w else "FP") for f, w in zip(m["fault_id"], m["in_fault_window"])]
    m["fault_start"] = [gt_by_id.get(f, {}).get("start_ts") if f else None for f in m["fault_id"]]
    return json.loads(m.to_json(orient="records"))


@app.get("/api/templates")
def templates(run: str | None = None):
    con, _, _ = _con(run)
    rows = _rows(con.execute("SELECT * FROM templates ORDER BY event_id"))
    con.close()
    return rows


@app.get("/api/transitions")
def transitions():
    f = ART_DIR / "transitions.json"
    if not f.exists():
        return {"nodes": [], "edges": []}
    return json.loads(f.read_text())


_score_cache: dict = {}


@app.get("/api/scoreboard")
def scoreboard(run: str | None = None):
    key = run or "live"
    hit = _score_cache.get(key)
    if hit and time.time() - hit[0] < 3:
        return hit[1]
    con, _, replay = _con(run)
    out = live.scoreboard(con, DETECTORS)
    now = _now(con, replay)
    out["lit"] = {d: bool(con.execute("SELECT 1 FROM alerts WHERE detector = ? AND ts > ? LIMIT 1",
                                      (d, now - 30)).fetchone()) for d in DETECTORS}
    out["counts"] = dict(con.execute("SELECT detector, COUNT(*) FROM alerts GROUP BY detector").fetchall())
    con.close()
    _score_cache[key] = (time.time(), out)
    return out


@app.get("/api/incidents")
def incidents(run: str | None = None):
    from logpulse.eval.incidents import daily_summary, incident_reports
    con, p, _ = _con(run)
    name = run or (p.run if p else "")
    out = {"reports": [{"fault_id": f, "markdown": md} for f, md in incident_reports(con, name)],
           "summary": daily_summary(con)}
    con.close()
    return out


@app.get("/api/runs")
def runs():
    return sorted({p.stem for d in (LIVE_RUNS, RUNS) for p in d.glob("*.db")})


# ------------------------------------------------------------------ faults (proxy to chaos)
@app.get("/api/faults")
def faults():
    try:
        return httpx.get(f"{CHAOS_URL}/faults", timeout=5).json()
    except httpx.HTTPError as e:
        return JSONResponse(status_code=502, content={"error": str(e)})


@app.post("/api/faults/{fault}")
def fault(fault: str, duration: float | None = None):
    params = {"duration": duration} if duration else {}
    path = "restore" if fault == "restore" else f"faults/{fault}"
    try:
        return httpx.post(f"{CHAOS_URL}/{path}", params=params, timeout=30).json()
    except httpx.HTTPError as e:
        return JSONResponse(status_code=502, content={"error": str(e)})


@app.post("/api/faults/{fault}/end")
def fault_end(fault: str):
    try:
        return httpx.post(f"{CHAOS_URL}/faults/{fault}/end", timeout=60).json()
    except httpx.HTTPError as e:
        return JSONResponse(status_code=502, content={"error": str(e)})


# ------------------------------------------------------------------ writes
@app.post("/api/ground_truth")
def ground_truth(row: dict = Body(...)):
    state["pipeline"].add_ground_truth(row)
    return {"ok": True}


@app.post("/api/feedback")
def feedback(body: dict = Body(...)):
    p = state["pipeline"]
    with p.lock:
        p.con.execute("INSERT INTO feedback VALUES (?, ?, ?)", (body["trace_id"], time.time(),
                                                                body.get("note", "false alarm")))
        p.con.commit()
    return {"ok": True}


@app.post("/api/admin/reset")
def reset(body: dict = Body(...)):
    run = body.get("run") or time.strftime("run_%Y%m%d_%H%M%S")
    mode = body.get("mode", "detect" if (ART_DIR / "deeplog.pt").exists() else "collect")
    p = state["pipeline"]
    if p is not None:
        with p.lock:
            start(run, mode)
    else:
        start(run, mode)
    return {"run": run, "mode": mode, "version": state["pipeline"].version}


@app.post("/api/admin/export")
def export():
    p = state["pipeline"]
    dest = p.export(RUNS / f"{p.run}.db")
    return {"run": p.run, "exported_to": str(dest)}


@app.get("/ui")
def ui():
    return FileResponse(ROOT / "dashboard" / "react" / "index.html")
