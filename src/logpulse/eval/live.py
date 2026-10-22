"""Live-run scoring: alerts vs fault ground truth (note 14 'Metric definitions').

Shared by the dashboard scoreboard (live) and scripts/score_live.py (reported numbers).

Rules
- A fault run f = [s_f, e_f] is *detected* by a method if it raises >= 1 alert that maps
  to f within [s_f, e_f + grace] (grace = 30 s).
- An alert maps to f if it falls in that window and concerns the target: its service is
  the target, or its trace touched the target (logged by it, or called it). System-level
  alerts with no trace (B2 error rate) map to any fault active in the window.
- TTD = first mapped alert - s_f (detected runs only; median + IQR reported).
- False alarm = alert mapping to no fault, outside every fault window (+grace). Counted
  raw and debounced (one per detector+service per 10 s, the same debounce B1 uses).
- Trace label (session-level P/R/F1): anomalous iff the trace started in
  [s_f, e_f + label_grace] and touched the target service.
- Deploy rows (type 'deploy', F7) are not faults; they define the post-deploy window.
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd

GRACE = 30.0
LABEL_GRACE = 5.0
DEBOUNCE = 10.0
SILENT = {"F3", "F4"}


def load(con) -> dict:
    q = lambda s: pd.read_sql_query(s, con)  # noqa: E731
    gt = q("SELECT * FROM ground_truth")
    alerts = q("SELECT id, detector, kind, ts, event_ts, trace_id, service, step, reason FROM alerts")
    sessions = q("SELECT trace_id, start_ts, end_ts, n_events, services, called, status_code FROM sessions")
    span = q("SELECT MIN(ts) AS t0, MAX(ts) AS t1, COUNT(*) AS n FROM raw_lines").iloc[0]
    return {"gt": gt, "alerts": alerts, "sessions": sessions, "t0": span["t0"], "t1": span["t1"], "n_lines": span["n"]}


def fault_code(fault_type: str) -> str:
    return str(fault_type).split("_")[0]


def _touched(sessions: pd.DataFrame) -> dict[str, set]:
    out = {}
    for r in sessions.itertuples():
        s = set(filter(None, str(r.services or "").split(","))) | set(filter(None, str(r.called or "").split(",")))
        out[r.trace_id] = s
    return out


def faults_only(gt: pd.DataFrame) -> pd.DataFrame:
    if gt.empty:
        return gt
    f = gt[gt["type"] != "deploy"].copy()
    now = time.time()
    f["end_ts"] = f["end_ts"].fillna(now)
    return f


def map_alerts(alerts: pd.DataFrame, gt: pd.DataFrame, sessions: pd.DataFrame, grace=GRACE) -> pd.DataFrame:
    a = alerts.copy()
    a["fault_id"] = None
    a["in_fault_window"] = False
    faults = faults_only(gt)
    if a.empty or faults.empty:
        return a
    touched = _touched(sessions)
    fid, inwin = [], []
    for r in a.itertuples():
        hit, win = None, False
        tid = r.trace_id if isinstance(r.trace_id, str) and r.trace_id != "-" else None
        # most recently started fault first, so overlapping grace windows credit the newer fault
        for f in faults.sort_values("start_ts", ascending=False).itertuples():
            if f.start_ts <= r.ts <= f.end_ts + grace:
                win = True
                tgt = f.target_service
                concerns = (r.service == tgt) or (tid is not None and tgt in touched.get(tid, set())) \
                    or (tid is None and r.detector == "B2_error_rate")
                if concerns:
                    hit = f.fault_id
                    break
        fid.append(hit)
        inwin.append(win)
    a["fault_id"] = fid
    a["in_fault_window"] = inwin
    return a


def debounce_count(a: pd.DataFrame, window=DEBOUNCE) -> int:
    n = 0
    for _, g in a.sort_values("ts").groupby(["detector", "service"], dropna=False):
        last = -1e18
        for t in g["ts"]:
            if t - last >= window:
                n += 1
                last = t
    return n


def fault_free_hours(gt, t0, t1, lo=None, hi=None, grace=GRACE) -> float:
    lo = t0 if lo is None else max(lo, t0)
    hi = t1 if hi is None else min(hi, t1)
    if hi is None or lo is None or hi <= lo:
        return 0.0
    busy = 0.0
    for f in faults_only(gt).itertuples():
        a, b = max(lo, f.start_ts), min(hi, f.end_ts + grace)
        busy += max(0.0, b - a)
    return max(hi - lo - busy, 0.0) / 3600.0


def detection_table(mapped: pd.DataFrame, gt: pd.DataFrame, detectors) -> pd.DataFrame:
    rows = []
    for f in faults_only(gt).itertuples():
        for d in detectors:
            hits = mapped[(mapped["detector"] == d) & (mapped["fault_id"] == f.fault_id)]
            first = hits["ts"].min() if len(hits) else None
            rows.append({"fault_id": f.fault_id, "fault": fault_code(f.type), "type": f.type,
                         "target": f.target_service, "detector": d, "detected": first is not None,
                         "ttd": (first - f.start_ts) if first is not None else np.nan,
                         "start_ts": f.start_ts, "end_ts": f.end_ts})
    return pd.DataFrame(rows)


def false_alarms(mapped: pd.DataFrame, gt: pd.DataFrame, t0, t1, detectors, lo=None, hi=None) -> pd.DataFrame:
    hours = fault_free_hours(gt, t0, t1, lo, hi)
    rows = []
    for d in detectors:
        fa = mapped[(mapped["detector"] == d) & mapped["fault_id"].isna() & ~mapped["in_fault_window"]]
        if lo is not None:
            fa = fa[fa["ts"] >= lo]
        if hi is not None:
            fa = fa[fa["ts"] <= hi]
        rows.append({"detector": d, "fa_raw": len(fa), "fa_debounced": debounce_count(fa), "hours": hours,
                     "fa_per_h": debounce_count(fa) / hours if hours > 0 else np.nan,
                     "fa_raw_per_h": len(fa) / hours if hours > 0 else np.nan})
    return pd.DataFrame(rows)


def trace_labels(sessions: pd.DataFrame, gt: pd.DataFrame, label_grace=LABEL_GRACE) -> pd.Series:
    touched = _touched(sessions)
    y = pd.Series(0, index=sessions["trace_id"].values, dtype=int)
    for f in faults_only(gt).itertuples():
        m = (sessions["start_ts"] >= f.start_ts) & (sessions["start_ts"] <= f.end_ts + label_grace)
        for tid in sessions.loc[m, "trace_id"]:
            if f.target_service in touched.get(tid, set()):
                y[tid] = 1
    return y


def session_prf(alerts: pd.DataFrame, sessions: pd.DataFrame, gt: pd.DataFrame, detectors) -> pd.DataFrame:
    from logpulse.eval.metrics import prf
    y = trace_labels(sessions, gt)
    rows = []
    for d in detectors:
        flagged = set(alerts.loc[alerts["detector"] == d, "trace_id"].dropna())
        yhat = y.index.isin(list(flagged)).astype(int)
        rows.append({"detector": d, **prf(y.values, yhat), "n_traces": len(y), "n_anomalous": int(y.sum())})
    return pd.DataFrame(rows)


def lines_to_read(con, gt: pd.DataFrame, mapped: pd.DataFrame, detector: str) -> pd.DataFrame:
    rows = []
    for f in faults_only(gt).itertuples():
        n_window = con.execute("SELECT COUNT(*) FROM raw_lines WHERE ts BETWEEN ? AND ?",
                               (f.start_ts, f.end_ts)).fetchone()[0]
        hits = mapped[(mapped["detector"] == detector) & (mapped["fault_id"] == f.fault_id)].sort_values("ts")
        attached = None
        if len(hits) and isinstance(hits.iloc[0]["trace_id"], str):
            attached = con.execute("SELECT COUNT(*) FROM raw_lines WHERE trace_id = ?",
                                   (hits.iloc[0]["trace_id"],)).fetchone()[0]
        rows.append({"fault_id": f.fault_id, "fault": fault_code(f.type), "lines_in_window": n_window,
                     "lines_attached": attached})
    return pd.DataFrame(rows)


def scoreboard(con, detectors) -> dict:
    """Compact live numbers for the dashboard."""
    d = load(con)
    mapped = map_alerts(d["alerts"], d["gt"], d["sessions"])
    det = detection_table(mapped, d["gt"], detectors)
    fa = false_alarms(mapped, d["gt"], d["t0"], d["t1"], detectors)
    out = {}
    for name in detectors:
        dd = det[det["detector"] == name] if len(det) else det
        m = mapped[mapped["detector"] == name] if len(mapped) else mapped
        tp = int(m["fault_id"].notna().sum()) if len(m) else 0
        fa_row = fa[fa["detector"] == name].iloc[0] if len(fa) else None
        out[name] = {
            "tp_alerts": tp,
            "fp_alerts": int(fa_row["fa_debounced"]) if fa_row is not None else 0,
            "faults_detected": int(dd["detected"].sum()) if len(dd) else 0,
            "faults_missed": int((~dd["detected"]).sum()) if len(dd) else 0,
            "mttd": float(np.nanmedian(dd["ttd"])) if len(dd) and dd["detected"].any() else None,
            "fa_per_h": float(fa_row["fa_per_h"]) if fa_row is not None and not np.isnan(fa_row["fa_per_h"]) else None,
        }
    return {"detectors": out, "faults": det.to_dict("records") if len(det) else []}
