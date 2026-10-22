"""Tune every live detector on the *tuning* runs only (schedule seeds 1-3), never on test runs.

    python -m logpulse.online.tune_demo --runs tune_s1 tune_s2 --deploy-run tune_deploy

- DeepLog decision rules: g (top-g), p (top-p), theta (surprise) -> best trace-level F1.
- Matcher tau: best trace-level F1 on the deploy tuning run (policy P4 + top-p).
- B1 keyword debounce and B2 error-rate threshold: best fault-level F1 when replayed on
  the tuning runs' raw lines (B3 health cannot be replayed; it keeps the spec 10 s x 3).
- RF baseline: trained on the tuning runs' labelled traces (event-count vectors).
"""
from __future__ import annotations

import argparse
import json
import pickle
import re

import numpy as np
import pandas as pd
import torch

from logpulse.eval import live
from logpulse.eval.metrics import prf, write_results
from logpulse.features.vectorize import count_matrix
from logpulse.models.baselines import make_supervised
from logpulse.models.deeplog import DeepLog, step_stats
from logpulse.online.detector import B1_RE
from logpulse.online.replay import as_sessions, build_traces, load_raw, replay
from logpulse.online.sessionizer import TERMINAL_RE
from logpulse.paths import ARTIFACTS

G_GRID = list(range(1, 16))
P_GRID = [0.8, 0.9, 0.95, 0.99, 0.995, 0.999, 0.9999]
TAU_GRID = [0.4, 0.5, 0.6, 0.7, 0.8]
B1_DEBOUNCE = [5, 10, 30, 60]
B2_THRESH = [0.05, 0.08, 0.1, 0.15, 0.2, 0.3]


def labelled(run, art, tau=None):
    rp = replay(run, art, tau)
    _, gt, _ = load_raw(run)
    y = live.trace_labels(as_sessions(rp.traces), gt).reindex(rp.traces["trace_id"]).to_numpy()
    return rp, gt, y


def b1_replay(raw, debounce):
    out, last = [], {}
    for r in raw.itertuples():
        if B1_RE.search(r.level) or B1_RE.search(r.msg):
            if r.ts - last.get(r.service, -1e18) >= debounce:
                last[r.service] = r.ts
                out.append(("B1_keyword", r.ts, r.service, r.trace_id))
    return out


def b2_replay(raw, thr, window=60.0, min_n=20):
    out, w, last = [], [], -1e18
    for r in raw[raw["service"] == "gateway"].itertuples():
        m = TERMINAL_RE.match(r.msg)
        if not m:
            continue
        w.append((r.ts, int(m.group(1)) // 100 != 2))
        while w and w[0][0] < r.ts - window:
            w.pop(0)
        errs = sum(e for _, e in w)
        if len(w) >= min_n and errs / len(w) > thr and r.ts - last >= window:
            last = r.ts
            out.append(("B2_error_rate", r.ts, "gateway", None))
    return out


def fault_f1(alerts, gt, sessions, t0, t1):
    a = pd.DataFrame(alerts, columns=["detector", "ts", "service", "trace_id"])
    if a.empty:
        return 0.0, 0.0, 0.0
    m = live.map_alerts(a, gt, sessions)
    det = live.detection_table(m, gt, [a["detector"].iloc[0]])
    dr = det["detected"].mean() if len(det) else 0.0
    prec = live.debounce_count(m[m["fault_id"].notna()]) / max(live.debounce_count(m), 1)
    f1 = 2 * dr * prec / (dr + prec) if dr + prec else 0.0
    return f1, dr, prec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", required=True)
    ap.add_argument("--deploy-run", default=None)
    ap.add_argument("--art", default=str(ARTIFACTS / "demo"))
    args = ap.parse_args()
    torch.set_num_threads(2)
    from pathlib import Path
    art = Path(args.art)
    model, ck = DeepLog.load(art / "deeplog.pt")
    h = ck["h"]
    cfg = json.loads((art / "config.json").read_text())
    rows = []

    seqs, ys, raws = [], [], []
    for run in args.runs:
        rp, gt, y = labelled(run, art)
        seqs += list(rp.traces["p1"])
        ys.append(y)
        raws.append((rp, gt))
        print(f"{run}: {len(y):,} traces, {int(y.sum()):,} anomalous by the labelling rule")
    y = np.concatenate(ys)
    st = step_stats(model, seqs, h)

    def best(rule, grid):
        res = [(q, prf(y, st.predict(rule, q))) for q in grid]
        for q, m in res:
            rows.append({"dataset": "demo", "split": "tune", "model": f"DeepLog/{rule}", "seed": 0,
                         "precision": m["precision"], "recall": m["recall"], "f1": m["f1"],
                         "notes": f"tuning;param={q}"})
        return max(res, key=lambda r: r[1]["f1"])

    g, mg = best("topg", G_GRID)
    p, mp = best("topp", P_GRID)
    s = -st.logp[np.isfinite(st.logp)]
    theta, mt = best("surprise", list(np.unique(np.round(np.quantile(s, np.linspace(0.5, 0.9999, 40)), 3))))
    print(f"g={g} F1={mg['f1']:.3f} | p={p} F1={mp['f1']:.3f} | theta={theta} F1={mt['f1']:.3f}")
    cfg.update({"g": int(g), "p": float(p), "theta": float(theta)})

    if args.deploy_run:
        rp, gt, yd = labelled(args.deploy_run, art)
        res = []
        for tau in TAU_GRID:
            tr = build_traces(rp.raw, rp.templates, tau)
            std = step_stats(model, list(tr["p4"]), h)
            m = prf(yd, std.predict("topp", p))
            res.append((tau, m))
            rows.append({"dataset": "demo", "split": "tune", "model": "DeepLog+P4", "seed": 0, **m,
                         "notes": f"tuning;tau={tau};deploy_run={args.deploy_run}"})
            print(f"  tau={tau}: P={m['precision']:.3f} R={m['recall']:.3f} F1={m['f1']:.3f}")
        cfg["tau"] = float(max(res, key=lambda r: (round(r[1]["f1"], 3), r[0]))[0])
        print("tau =", cfg["tau"])

    # conventional baselines, replayed on the tuning runs' raw lines
    def tune_baseline(name, grid, fn):
        scores = []
        for q in grid:
            f1s = []
            for rp, gt in raws:
                ses = as_sessions(rp.traces)
                f1s.append(fault_f1(fn(rp.raw, q), gt, ses, rp.raw["ts"].min(), rp.raw["ts"].max())[0])
            scores.append((q, float(np.mean(f1s))))
            rows.append({"dataset": "demo", "split": "tune", "model": name, "seed": 0, "metric": "fault_f1",
                         "value": scores[-1][1], "notes": f"tuning;param={q}"})
        return max(scores, key=lambda s: s[1])[0]

    cfg["b1_debounce"] = float(tune_baseline("B1_keyword", B1_DEBOUNCE, b1_replay))
    cfg["b2_threshold"] = float(tune_baseline("B2_error_rate", B2_THRESH, b2_replay))
    print(f"B1 debounce={cfg['b1_debounce']}s  B2 threshold={cfg['b2_threshold']}")

    # RF on labelled tuning traces
    X = count_matrix(seqs, model.n_events)
    rf = make_supervised("RF", 0).fit(X, y)
    (art / "rf.pkl").write_bytes(pickle.dumps(rf))
    cfg["rf_trained_on"] = args.runs
    cfg["tuned_on"] = args.runs + ([args.deploy_run] if args.deploy_run else [])
    (art / "config.json").write_text(json.dumps(cfg, indent=2))
    write_results("E8", rows, tag="tuning;")
    print(json.dumps(cfg, indent=2))


if __name__ == "__main__":
    main()
