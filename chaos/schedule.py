"""Seeded fault schedule (note 14 'Measurement protocol').

Each fault type x runs, random order, jittered duration, >= gap seconds of normal traffic
between faults. Seeds 1-3 are tuning runs, 4+ are reported test runs.

    python chaos/schedule.py --seed 4 --faults F1 F2 F3 F4 F5 F6 --runs 1
    python chaos/schedule.py --seed 4 --deploy --faults F1 F3 F4 --runs 1   # F7 block
"""
from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

import httpx


def plan(seed: int, faults, runs: int, duration: float, gap: float, jitter: float = 0.2):
    rng = random.Random(seed)
    items = [f for f in faults for _ in range(runs)]
    rng.shuffle(items)
    return [{"fault": f, "duration": round(duration * rng.uniform(1 - jitter, 1 + jitter)),
             "gap_after": round(gap * rng.uniform(1, 1 + jitter))} for f in items]


def execute(steps, api: str, warmup: float, deploy: bool, run: str | None, log=print):
    with httpx.Client(timeout=60) as c:
        if warmup:
            log(f"warm-up {warmup:.0f}s")
            time.sleep(warmup)
        if deploy:
            log("F7 deploy payment:v2")
            c.post(f"{api}/faults/F7", params={"run": run} if run else {}).raise_for_status()
            time.sleep(60)
        for i, s in enumerate(steps):
            log(f"[{i + 1}/{len(steps)}] {s['fault']} for {s['duration']}s, then {s['gap_after']}s normal")
            params = {"duration": s["duration"], **({"run": run} if run else {})}
            c.post(f"{api}/faults/{s['fault']}", params=params).raise_for_status()
            time.sleep(s["duration"] + s["gap_after"])
        if deploy:
            c.post(f"{api}/faults/F7/end").raise_for_status()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--faults", nargs="+", default=["F1", "F2", "F3", "F4", "F5", "F6"])
    ap.add_argument("--runs", type=int, default=10, help="runs per fault type (protocol: 10)")
    ap.add_argument("--duration", type=float, default=150, help="seconds per fault (protocol: 2-3 min)")
    ap.add_argument("--gap", type=float, default=180, help="normal traffic between faults (protocol: >= 3 min)")
    ap.add_argument("--warmup", type=float, default=0)
    ap.add_argument("--deploy", action="store_true", help="wrap the schedule in an F7 deploy block")
    ap.add_argument("--api", default="http://localhost:9100")
    ap.add_argument("--run", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    steps = plan(args.seed, args.faults, args.runs, args.duration, args.gap)
    out = Path(__file__).with_name(f"schedule_seed{args.seed}{'_deploy' if args.deploy else ''}.json")
    out.write_text(json.dumps({"seed": args.seed, "steps": steps}, indent=2))
    print(f"{len(steps)} faults, ~{sum(s['duration'] + s['gap_after'] for s in steps) / 60:.0f} min -> {out.name}")
    if not args.dry_run:
        execute(steps, args.api, args.warmup, args.deploy, args.run)


if __name__ == "__main__":
    main()
