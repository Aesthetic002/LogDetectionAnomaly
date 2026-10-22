"""Write markdown incident reports for one run (or every test run) into reports/incidents/.

    python scripts/incident_report.py --run test_s4
    python scripts/incident_report.py --all
"""
import argparse

from logpulse import store
from logpulse.eval.incidents import daily_summary, incident_reports
from logpulse.paths import REPORTS, RUNS


def write(run):
    con = store.connect(RUNS / f"{run}.db", readonly=True)
    out = REPORTS / "incidents"
    out.mkdir(parents=True, exist_ok=True)
    for fid, md in incident_reports(con, run):
        (out / f"{run}__{fid}.md").write_text(md, encoding="utf-8")
    s = daily_summary(con)
    (out / f"{run}__summary.md").write_text(
        f"# Run summary — {run}\n\n" + "\n".join(f"- **{k}**: {v}" for k, v in s.items()) + "\n", encoding="utf-8")
    print(run, "->", out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    for r in sorted(p.stem for p in RUNS.glob("test_*.db")) if a.all else [a.run]:
        write(r)
