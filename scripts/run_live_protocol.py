"""Live measurement protocol (note 14), REDUCED by default — flags give the full protocol.

    python scripts/run_live_protocol.py normal --minutes 30          # training data (collect mode)
    python scripts/run_live_protocol.py tune                         # seeds 1-2 + deploy tuning run (seed 3)
    python scripts/run_live_protocol.py test                         # seeds 4-6, fault-free block, deploy seeds 7-8

Full protocol: --runs-per-fault 10 --duration 150 --gap 180 --fault-free-min 120 --deploy-min 30 ...
Each run: detector reset into a new run DB -> warm-up -> seeded schedule under load -> export.
docker stats are sampled every 15 s into data/demo/runs/<run>_stats.csv (Table E overhead).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "chaos"))
from schedule import execute, plan  # noqa: E402

DET = "http://localhost:9000"
CHAOS = "http://localhost:9100"
RUNS = ROOT / "data" / "demo" / "runs"


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def sample_stats(path: Path, stop: threading.Event):
    with open(path, "w") as fh:
        fh.write("t,name,cpu_pct,mem_mb\n")
        while not stop.is_set():
            out = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{json .}}"],
                                 capture_output=True, text=True).stdout
            t = time.time()
            for line in out.splitlines():
                d = json.loads(line)
                mem = d["MemUsage"].split("/")[0].strip()
                mb = float(mem[:-3]) * (1024 if mem.endswith("GiB") else 1) if mem[-3:] in ("MiB", "GiB") else 0.0
                fh.write(f"{t:.0f},{d['Name']},{d['CPUPerc'].rstrip('%')},{mb:.1f}\n")
            fh.flush()
            stop.wait(15)


def run(name: str, seed: int, minutes_load: float, schedule=None, deploy=False, warmup=120, mode="detect", rate=20):
    log(f"=== run {name} (seed {seed}, mode {mode})")
    httpx.post(f"{CHAOS}/restore", timeout=60)
    httpx.post(f"{DET}/api/admin/reset", json={"run": name, "mode": mode}, timeout=30).raise_for_status()
    stop = threading.Event()
    th = threading.Thread(target=sample_stats, args=(RUNS / f"{name}_stats.csv", stop), daemon=True)
    th.start()
    load = subprocess.Popen([sys.executable, str(ROOT / "scripts" / "load.py"), "--rate", str(rate),
                             "--duration", str(int(minutes_load * 60)), "--seed", str(seed)],
                            stdout=open(RUNS / f"{name}_load.log", "w"), stderr=subprocess.STDOUT)
    t0 = time.time()
    if schedule is not None:
        execute(schedule, CHAOS, warmup, deploy, name, log=log)
    remaining = minutes_load * 60 - (time.time() - t0)
    if remaining > 0:
        time.sleep(remaining)
    load.wait()
    time.sleep(8)  # let the reorder buffer and idle timeouts drain
    httpx.post(f"{CHAOS}/restore", timeout=60)
    stop.set()
    r = httpx.post(f"{DET}/api/admin/export", timeout=120).json()
    log(f"=== {name} done -> {r['exported_to']}")


def minutes(steps, warmup, deploy):
    return (warmup + sum(s["duration"] + s["gap_after"] for s in steps) + (60 if deploy else 0)) / 60 + 0.5


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["normal", "tune", "test"])
    ap.add_argument("--minutes", type=float, default=30)
    ap.add_argument("--faults", nargs="+", default=["F1", "F2", "F3", "F4", "F5", "F6"])
    ap.add_argument("--runs-per-fault", type=int, default=1, help="per seed (protocol: 10 total)")
    ap.add_argument("--duration", type=float, default=75)
    ap.add_argument("--gap", type=float, default=105)
    ap.add_argument("--warmup", type=float, default=120)
    ap.add_argument("--tune-seeds", nargs="+", type=int, default=[1, 2])
    ap.add_argument("--test-seeds", nargs="+", type=int, default=[4, 5, 6])
    ap.add_argument("--deploy-tune-seed", type=int, default=3)
    ap.add_argument("--deploy-test-seeds", nargs="+", type=int, default=[7, 8])
    ap.add_argument("--deploy-faults", nargs="+", default=["F1", "F3", "F4"])
    ap.add_argument("--fault-free-min", type=float, default=20)
    ap.add_argument("--rate", type=float, default=20)
    a = ap.parse_args()

    if a.phase == "normal":
        run("normal", 7, a.minutes, mode="collect", warmup=0, rate=a.rate)
        return
    if a.phase == "tune":
        for s in a.tune_seeds:
            st = plan(s, a.faults, a.runs_per_fault, a.duration, a.gap)
            run(f"tune_s{s}", s, minutes(st, a.warmup, False), st, warmup=a.warmup, rate=a.rate)
        st = plan(a.deploy_tune_seed, a.deploy_faults, 1, a.duration, a.gap)
        run("tune_deploy", a.deploy_tune_seed, minutes(st, a.warmup, True), st, deploy=True, warmup=a.warmup,
            rate=a.rate)
        return
    for s in a.test_seeds:
        st = plan(s, a.faults, a.runs_per_fault, a.duration, a.gap)
        run(f"test_s{s}", s, minutes(st, a.warmup, False), st, warmup=a.warmup, rate=a.rate)
    run("test_faultfree", 100, a.fault_free_min, None, warmup=0, rate=a.rate)
    for s in a.deploy_test_seeds:
        st = plan(s, a.deploy_faults, 1, a.duration, a.gap)
        run(f"test_deploy_s{s}", s, minutes(st, a.warmup, True), st, deploy=True, warmup=a.warmup, rate=a.rate)


if __name__ == "__main__":
    main()
