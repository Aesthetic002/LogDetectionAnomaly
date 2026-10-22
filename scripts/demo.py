"""One-command demo (~8 min): known-good scenarios from the demo script in docs/12.

    python scripts/demo.py            # then open http://localhost:8501 (and :9000/ui)

  0:00  warm-up, normal traffic (topology all green)
  1:00  F1 Slow payment        error-visible: keyword alert AND our model fire
  2:30  F3 Skip stock step     silent: no ERROR line, keyword / error-rate stay dark, our model fires
  4:00  F7 Deploy reworded logs  vanilla DeepLog alerts on every request, ours stays calm
  6:30  restore, run exported + scored, incident reports written
"""
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
DET, CHAOS = "http://localhost:9000", "http://localhost:9100"
STEPS = [(60, None, 0), (0, "F1", 60), (30, None, 0), (0, "F3", 60), (30, None, 0), (0, "F7", 150), (30, None, 0)]


def say(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def main():
    run = sys.argv[1] if len(sys.argv) > 1 else time.strftime("demo_%H%M")
    httpx.post(f"{CHAOS}/restore", timeout=120)
    httpx.post(f"{DET}/api/admin/reset", json={"run": run, "mode": "detect"}, timeout=900).raise_for_status()
    total = sum(w + d for w, _, d in STEPS) + 10
    load = subprocess.Popen([sys.executable, str(ROOT / "scripts" / "load.py"), "--rate", "20", "--duration", str(total)],
                            stdout=subprocess.DEVNULL)
    say(f"run '{run}' started — dashboard http://localhost:8501 · React page http://localhost:9000/ui")
    for wait, fault, dur in STEPS:
        if wait:
            say(f"normal traffic {wait}s")
            time.sleep(wait)
        if fault:
            if fault == "F7":
                httpx.post(f"{CHAOS}/faults/F7", params={"run": run}, timeout=120).raise_for_status()
                say("F7 deploy payment:v2 (reworded logs) — watch vanilla vs ours")
                time.sleep(dur)
                httpx.post(f"{CHAOS}/faults/F7/end", timeout=120)
                say("F7 rolled back")
            else:
                httpx.post(f"{CHAOS}/faults/{fault}", params={"duration": dur, "run": run}, timeout=120).raise_for_status()
                say(f"{fault} injected for {dur}s")
                time.sleep(dur)
    load.wait()
    time.sleep(8)
    httpx.post(f"{DET}/api/admin/export", timeout=900)
    say("exported; scoring")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "demo_summary.py"), run])
    subprocess.run([sys.executable, str(ROOT / "scripts" / "incident_report.py"), "--run", run])


if __name__ == "__main__":
    main()
