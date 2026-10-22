"""Automatic incident reports (note 13 'Incident reports') from a run DB."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from logpulse.eval import live

PRIMARY = "deeplog_full"
COMPARE = [("B1_keyword", "keyword alert"), ("B2_error_rate", "error-rate threshold"), ("B3_health", "health check"),
           ("deeplog_vanilla", "vanilla DeepLog")]


def _t(ts) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%H:%M:%S.%f")[:-5]


def incident_reports(con, run: str = "") -> list[tuple[str, str]]:
    """Return [(fault_id, markdown)] — one report per ground-truth fault in the run."""
    d = live.load(con)
    mapped = live.map_alerts(d["alerts"], d["gt"], d["sessions"])
    info = {r[0]: json.loads(r[1]) for r in con.execute("SELECT key, value FROM run_info")}
    cfg = info.get("cfg", {})
    tpl = dict(con.execute("SELECT event_id, template FROM templates").fetchall())
    out = []
    for n, f in enumerate(live.faults_only(d["gt"]).sort_values("start_ts").itertuples(), 1):
        hits = mapped[(mapped["fault_id"] == f.fault_id)]
        prim = hits[hits["detector"] == PRIMARY].sort_values("ts")
        date = datetime.fromtimestamp(f.start_ts, timezone.utc).strftime("%Y-%m-%d")
        lines = [f"# Incident {date}-{n:02d} — {f.target_service} service", ""]
        lines.append(f"Window: {_t(f.start_ts)} – {_t(f.end_ts)} UTC (ground truth {f.fault_id} {f.type})  ")
        n_win = con.execute("SELECT COUNT(*) FROM raw_lines WHERE ts BETWEEN ? AND ?", (f.start_ts, f.end_ts)).fetchone()[0]
        if len(prim):
            a = prim.iloc[0]
            full = con.execute("SELECT * FROM alerts WHERE id = ?", (int(a["id"]),)).fetchone()
            lines.append(f"First alert: {_t(a['ts'])} (+{a['ts'] - f.start_ts:.1f} s) · Detector: DeepLog step-wise "
                         f"(top-p {cfg.get('p', '?')}, semantic matcher τ={cfg.get('tau', '?')})  ")
            sess = d["sessions"]
            in_win = sess[(sess["start_ts"] >= f.start_ts) & (sess["start_ts"] <= f.end_ts)]
            affected = prim["trace_id"].nunique()
            lines.append(f"Affected traces: {affected:,} of {len(in_win):,} "
                         f"({100 * affected / max(len(in_win), 1):.1f}%) started in the window  ")
            ev = con.execute("SELECT event_id, template, service, ts, raw_id FROM events WHERE trace_id = ? "
                             "ORDER BY ts, id", (a["trace_id"],)).fetchall()
            step = int(full["step"]) if full["step"] is not None else len(ev) - 1
            prev = ev[step - 1] if step > 0 and step - 1 < len(ev) else None
            cur = ev[step] if step < len(ev) else None
            if cur is not None:
                after = f' after E{prev["event_id"]} "{prev["template"]}"' if prev is not None else " at trace start"
                lines.append(f'First anomalous event: E{cur["event_id"]} "{cur["template"]}"{after}  ')
            expected = json.loads(full["expected"] or "[]")
            if expected:
                lines.append("Model expected instead: " + ", ".join(
                    f'E{e} "{tpl.get(e, t)}" (p={p:.2f})' for e, p, t in expected[:3]) + "  ")
            svc = prim.groupby("service")["trace_id"].nunique().sort_values(ascending=False)
            lines.append("Services involved: " + ", ".join(f"{s} ({c} traces)" for s, c in svc.items()) + "  ")
            attached = con.execute("SELECT COUNT(*) FROM raw_lines WHERE trace_id = ?", (a["trace_id"],)).fetchone()[0]
            lines.append(f"Lines in window: {n_win:,} · Lines attached to report: {attached}  ")
        else:
            lines.append("First alert: **not detected by the step-wise model**  ")
            lines.append(f"Lines in window: {n_win:,}  ")
        comp = []
        for det, label in COMPARE:
            h = hits[hits["detector"] == det]
            comp.append(f"{label} +{h['ts'].min() - f.start_ts:.1f} s" if len(h) else f"{label} —")
        lines.append("Comparison: " + " · ".join(comp))
        if len(prim):
            lines += ["", "Sample raw lines (offending trace):", "", "```"]
            for r in con.execute("SELECT ts, container, line_no, level, msg FROM raw_lines WHERE trace_id = ? "
                                 "ORDER BY ts, id LIMIT 20", (prim.iloc[0]["trace_id"],)):
                lines.append(f"{_t(r['ts'])} {r['container']}#{r['line_no']} {r['level']:<7} {r['msg']}")
            lines.append("```")
        lines += ["", f"*Generated automatically from run `{run}`; verdicts from the injector's ground truth.*"]
        out.append((f.fault_id, "\n".join(lines)))
    return out


def daily_summary(con) -> dict:
    d = live.load(con)
    n_traces = len(d["sessions"])
    al = d["alerts"]
    mapped = live.map_alerts(al, d["gt"], d["sessions"])
    fa = live.false_alarms(mapped, d["gt"], d["t0"], d["t1"], [PRIMARY])
    det = live.detection_table(mapped, d["gt"], [PRIMARY])
    new_t = con.execute("SELECT COUNT(*) FROM templates WHERE status != 'known'").fetchone()[0]
    return {
        "requests_processed": int(n_traces),
        "raw_lines": int(d["n_lines"] or 0),
        "anomalous_traces_by_service": al[al["detector"] == PRIMARY].groupby("service")["trace_id"].nunique().to_dict(),
        "new_templates": int(new_t),
        "false_alarms_per_h": float(fa["fa_per_h"].iloc[0]) if len(fa) and not np.isnan(fa["fa_per_h"].iloc[0]) else None,
        "detection_latency_s": det["ttd"].dropna().round(1).tolist() if len(det) else [],
        "faults_detected": f"{int(det['detected'].sum())}/{len(det)}" if len(det) else "0/0",
    }


def to_frame(reports) -> pd.DataFrame:
    return pd.DataFrame(reports, columns=["fault_id", "markdown"])
