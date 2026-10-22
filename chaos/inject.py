"""Fault injector (note 06 'Fault injection catalogue').

Runs as the `chaos` container with the Docker socket mounted. Every fault is applied
*and* recorded: a row goes to chaos/ground_truth.csv and to the detector's ground_truth
table at start (open) and at end (closed). Ground truth is never written by hand.

    uvicorn inject:app --port 9100          (inside the container)
    POST /faults/F3?duration=90             apply F3 for 90 s, then auto-restore
    POST /faults/F3/end                     end it now
    POST /restore                           end everything
    GET  /faults                            catalogue + active faults
"""
from __future__ import annotations

import csv
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import docker
import httpx
from fastapi import FastAPI, HTTPException

PROJECT = os.environ.get("COMPOSE_PROJECT", "logpulse")
DETECTOR_URL = os.environ.get("DETECTOR_URL", "http://detector:9000")
GT_CSV = Path(os.environ.get("GROUND_TRUTH_CSV", Path(__file__).with_name("ground_truth.csv")))

CATALOGUE = {
    "F1": {"type": "F1_payment_latency", "target": "payment", "how": "mode", "service": "payment", "mode": "slow",
           "label": "Slow payment", "visible_error": "yes"},
    "F2": {"type": "F2_payment_down", "target": "payment", "how": "stop", "service": "payment",
           "label": "Stop payment", "visible_error": "yes"},
    "F3": {"type": "F3_skip_reserve", "target": "orders", "how": "mode", "service": "orders", "mode": "skip_reserve",
           "label": "Skip stock step", "visible_error": "no"},
    "F4": {"type": "F4_retry_storm", "target": "payment", "how": "mode", "service": "payment", "mode": "retry_storm",
           "label": "Retry storm", "visible_error": "partly"},
    "F5": {"type": "F5_db_exhaustion", "target": "inventory", "how": "pause", "service": "db",
           "label": "DB exhaustion", "visible_error": "yes"},
    "F6": {"type": "F6_inventory_paused", "target": "inventory", "how": "pause", "service": "inventory",
           "label": "Pause inventory", "visible_error": "partly"},
    "F7": {"type": "deploy", "target": "payment", "how": "deploy", "service": "payment",
           "label": "Deploy reworded logs", "visible_error": "-"},
}

app = FastAPI(title="LogPulse fault injector")
client = docker.from_env()
lock = threading.RLock()
active: dict[str, dict] = {}


def _containers(service: str, all_=True):
    return client.containers.list(all=all_, filters={"label": [f"com.docker.compose.project={PROJECT}",
                                                                f"com.docker.compose.service={service}"]})


def _payment():
    """The payment container currently serving traffic (v1 or the v2 'deploy')."""
    for svc in ("payment", "payment-v2"):
        for c in _containers(svc):
            if c.status == "running":
                return c
    return _containers("payment")[0]


def _set_mode(service: str, mode: str):
    url = f"http://{service}:8000/admin/fault"
    for _ in range(20):
        try:
            httpx.post(url, json={"mode": mode}, timeout=3).raise_for_status()
            return
        except httpx.HTTPError:
            time.sleep(0.5)
    raise RuntimeError(f"could not set fault mode on {service}")


def _wait_healthy(host: str, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if httpx.get(f"http://{host}:8000/health", timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.3)


def _apply(fid: str) -> dict:
    f = CATALOGUE[fid]
    ctx = {}
    if f["how"] == "mode":
        _set_mode(f["service"], f["mode"])
    elif f["how"] == "stop":
        c = _payment()
        ctx["container"] = c.name
        c.stop(timeout=2)
    elif f["how"] == "pause":
        c = _containers(f["service"])[0]
        ctx["container"] = c.name
        c.pause()
    elif f["how"] == "deploy":
        v2 = _containers("payment-v2")
        if not v2:
            raise HTTPException(500, "payment-v2 container missing: run `docker compose --profile deploy create payment-v2`")
        v2[0].start()
        _wait_healthy("payment-v2")
        for c in _containers("payment"):
            if c.status == "running":
                c.stop(timeout=2)
    return ctx


def _restore(fid: str, ctx: dict):
    f = CATALOGUE[fid]
    if f["how"] == "mode":
        _set_mode(f["service"], "none")
    elif f["how"] == "stop":
        client.containers.get(ctx["container"]).start()
        _wait_healthy("payment")
    elif f["how"] == "pause":
        client.containers.get(ctx["container"]).unpause()
    elif f["how"] == "deploy":
        _containers("payment")[0].start()
        _wait_healthy("payment")
        for c in _containers("payment-v2"):
            if c.status == "running":
                c.stop(timeout=2)


def _iso(t: float | None) -> str:
    return "" if t is None else datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _record(row: dict, final: bool):
    try:
        httpx.post(f"{DETECTOR_URL}/api/ground_truth", json=row, timeout=5)
    except httpx.HTTPError as e:
        print("[chaos] could not notify detector:", e, flush=True)
    if final:
        new = not GT_CSV.exists()
        with open(GT_CSV, "a", newline="") as fh:
            w = csv.writer(fh)
            if new:
                w.writerow(["fault_id", "type", "target_service", "start_ts", "end_ts", "run_id"])
            w.writerow([row["fault_id"], row["type"], row["target_service"], _iso(row["start_ts"]),
                        _iso(row["end_ts"]), row["run_id"]])


def _current_run() -> str:
    try:
        return httpx.get(f"{DETECTOR_URL}/api/status", timeout=3).json().get("run") or "unknown"
    except httpx.HTTPError:
        return "unknown"


@app.get("/faults")
def faults():
    return {"catalogue": CATALOGUE, "active": list(active.values())}


@app.post("/faults/{fid}")
def start_fault(fid: str, duration: float | None = None, run: str | None = None):
    fid = fid.upper()
    if fid not in CATALOGUE:
        raise HTTPException(404, f"unknown fault {fid}")
    with lock:
        if fid in active:
            raise HTTPException(409, f"{fid} already active")
        start = time.time()
        ctx = _apply(fid)
        f = CATALOGUE[fid]
        row = {"fault_id": f"{fid}-{int(start * 1000)}", "type": f["type"], "target_service": f["target"],
               "start_ts": start, "end_ts": None, "run_id": run or _current_run(), "label": f["label"]}
        active[fid] = {**row, "ctx": ctx, "duration": duration}
        _record(row, final=False)
    if duration:
        threading.Timer(duration, lambda: _end_safe(fid, row["fault_id"])).start()
    print(f"[chaos] start {fid} {row['fault_id']} duration={duration}", flush=True)
    return row


def _end_safe(fid, fault_id):
    try:
        with lock:
            if fid in active and active[fid]["fault_id"] == fault_id:
                end_fault(fid)
    except Exception as e:  # never kill the timer thread silently
        print("[chaos] restore failed:", fid, e, flush=True)


@app.post("/faults/{fid}/end")
def end_fault(fid: str):
    fid = fid.upper()
    with lock:
        if fid not in active:
            raise HTTPException(404, f"{fid} not active")
        a = active.pop(fid)
        _restore(fid, a["ctx"])
        row = {k: a[k] for k in ("fault_id", "type", "target_service", "start_ts", "run_id", "label")}
        row["end_ts"] = time.time()
        _record(row, final=True)
    print(f"[chaos] end {fid} {row['fault_id']}", flush=True)
    return row


@app.post("/restore")
def restore_all():
    ended = []
    for fid in list(active):
        ended.append(end_fault(fid))
    for svc in ("payment", "orders"):
        try:
            _set_mode(svc, "none")
        except RuntimeError:
            pass
    return {"ended": ended}
