"""Train the demo-app detector from a recorded normal run.

    python -m logpulse.online.train_demo --run normal

1. Parsing accuracy (GA) on the run's messages vs the true log statements, for a sim_th
   sweep -> the demo sim_th (E1, demo rows).
2. Fresh Drain3 tree learned on the normal run -> artifacts/demo/drain_state.bin + template_map.json
3. Trace sequences, chronological 90/10 train/val (all normal) -> DeepLog (h=10) -> deeplog.pt
4. Empirical transition graph (Panel 5) -> transitions.json
5. config.json with defaults; tune_demo.py later sets g / p / theta / tau / baselines.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from collections import Counter

import numpy as np
import torch

from logpulse.eval.metrics import write_results
from logpulse.models.deeplog import DeepLog, train
from logpulse.online.demo_templates import statement_of
from logpulse.online.replay import load_raw
from logpulse.parsing.drain_parser import CachedMiner, grouping_accuracy, level_class, make_miner
from logpulse.paths import ARTIFACTS, FIRST_EVENT

SIM_GRID = [0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="normal")
    ap.add_argument("--h", type=int, default=10)
    ap.add_argument("--sim-th", type=float, default=None, help="default: best GA on this run")
    ap.add_argument("--out", default=str(ARTIFACTS / "demo"))
    ap.add_argument("--exclude-error-traces", action="store_true",
                    help="drop traces with ERROR lines (known incidents, e.g. host stalls) from the healthy training set")
    args = ap.parse_args()
    torch.set_num_threads(2)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    raw, _, _ = load_raw(args.run)
    raw = raw.sort_values("id")
    msgs = raw["msg"].tolist()
    truth = [statement_of(m) for m in msgs]
    print(f"{len(msgs):,} lines, {len(set(truth))} true statements, unknown={truth.count('?')}")

    # 1. GA sweep on the demo logs
    rows, best = [], (None, -1)
    for s in SIM_GRID:
        cm = CachedMiner(make_miner(sim_th=s))
        pred = [cm.learn_masked(cm.mask(m)) for m in msgs]
        ga = grouping_accuracy(truth, pred)
        rows.append({"dataset": "demo", "split": "-", "model": "Drain3", "seed": 0, "metric": "ga", "value": ga,
                     "notes": f"src=demo;sim_th={s};masking=True;templates={len(set(pred))};true={len(set(truth))}"})
        print(f"  sim_th={s}: GA={ga:.3f} templates={len(set(pred))}")
        if ga > best[1] + 1e-9:
            best = (s, ga)
    write_results("E1", rows, tag="src=demo")
    sim_th = args.sim_th or best[0]
    print(f"demo sim_th = {sim_th} (GA {best[1]:.3f})")

    # 2. frozen tree + template map
    state = out / "drain_state.bin"
    if state.exists():
        state.unlink()
    miner = make_miner(sim_th=sim_th)
    cm = CachedMiner(miner)
    eids = np.array([cm.learn_masked(cm.mask(m)) + 1 for m in msgs])
    from drain3.file_persistence import FilePersistence
    miner.persistence_handler = FilePersistence(str(state))
    miner.save_state("frozen after training")
    n_events = int(eids.max()) + 1
    events = {}
    for e in np.unique(eids):
        sel = raw[eids == e]
        events[int(e)] = {"template": miner.drain.id_to_cluster[int(e) - 1].get_template(),
                          "services": sorted(sel["service"].unique()),
                          "level_classes": sorted({level_class(lv) for lv in sel["level"].unique()}),
                          "count": int(len(sel))}
    version = hashlib.sha1(json.dumps(events, sort_keys=True).encode()).hexdigest()[:8]
    (out / "template_map.json").write_text(json.dumps({"n_events": n_events, "version": f"tm-{version}",
                                                        "sim_th": sim_th, "events": events}, indent=1))
    print(f"{n_events - FIRST_EVENT} templates, vocab {n_events}")

    # 3. traces -> DeepLog
    raw = raw.assign(eid=eids)
    ev = raw[raw["trace_id"] != "-"].sort_values(["trace_id", "ts", "id"], kind="stable")
    traces = [(g["ts"].iloc[0], g["eid"].to_numpy()) for _, g in ev.groupby("trace_id", sort=False)
              if not (args.exclude_error_traces and (g["level"] == "ERROR").any())]
    print(f"{len(traces):,} traces used ({ev['trace_id'].nunique() - len(traces)} excluded as known incidents)")
    traces.sort(key=lambda t: t[0])
    seqs = [t[1] for t in traces]
    n_tr = int(0.9 * len(seqs))
    model = DeepLog(n_events)
    t0 = time.time()
    log = train(model, seqs[:n_tr], h=args.h, val_seqs=seqs[n_tr:], seed=0)
    mv = f"deeplog-{version}-{time.strftime('%Y%m%d%H%M')}"
    model.save(out / "deeplog.pt", {"h": args.h, "version": mv, "epochs": log.epochs})
    print(f"trained on {n_tr:,} traces in {time.time() - t0:.0f}s ({log.epochs} epochs)")

    # 4. transitions
    cnt, start, end = Counter(), Counter(), Counter()
    for s in seqs[:n_tr]:
        start[int(s[0])] += 1
        end[int(s[-1])] += 1
        cnt.update(zip(map(int, s[:-1]), map(int, s[1:])))
    out_deg = Counter()
    for (a, _), c in cnt.items():
        out_deg[a] += c
    for e, c in end.items():
        out_deg[e] += c
    edges = [{"source": a, "target": b, "count": c, "prob": c / out_deg[a]} for (a, b), c in cnt.items()]
    edges += [{"source": "START", "target": e, "count": c, "prob": c / n_tr} for e, c in start.items()]
    edges += [{"source": e, "target": "END", "count": c, "prob": c / out_deg[e]} for e, c in end.items()]
    nodes = [{"id": e, **d} for e, d in events.items()]
    (out / "transitions.json").write_text(json.dumps({"nodes": nodes, "edges": edges}, indent=1))

    cfg_path = out / "config.json"
    cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
    cfg.update({"h": args.h, "model_version": mv, "trained_on": args.run, "train_traces": n_tr})
    cfg_path.write_text(json.dumps(cfg, indent=2))
    write_results("E8", [{"dataset": "demo", "split": "-", "model": "DeepLog", "seed": 0, "metric": "train_traces",
                          "value": n_tr, "train_time_s": log.seconds, "notes": f"trained_on={args.run};h={args.h};exclude_error_traces={args.exclude_error_traces}"}],
                  tag="trained_on=")
    print("artifacts ->", out)


if __name__ == "__main__":
    main()
