"""Regenerate every offline benchmark number + figure from data/processed.

    python scripts/run_all_experiments.py --config configs/experiments.yaml
    python scripts/run_all_experiments.py --only E2 E11
    python scripts/run_all_experiments.py --figures-only
"""
import argparse
import subprocess
import sys
import time

import yaml

from logpulse.eval import experiments as X
from logpulse.paths import REPORTS

RUNNERS = {"E1": X.e1, "E2": X.e2, "E2b": X.e2b, "E3": X.e3, "E4": X.e4, "E5": X.e5, "E7": X.e7,
           "E10": X.e10_bgl, "E11": X.e11}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/experiments.yaml")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--figures-only", action="store_true")
    args = ap.parse_args()
    cfg = yaml.safe_load(open(args.config))
    if not args.figures_only:
        for exp in args.only or cfg["experiments"]:
            t0 = time.time()
            print(f"==== {exp}", flush=True)
            RUNNERS[exp](cfg)
            print(f"==== {exp} done in {time.time() - t0:.0f}s", flush=True)
        env = subprocess.run([sys.executable, "-m", "pip", "freeze"], capture_output=True, text=True).stdout
        (REPORTS / "env.txt").write_text(env)
    from logpulse.eval import figures
    figures.make_all()


if __name__ == "__main__":
    main()
