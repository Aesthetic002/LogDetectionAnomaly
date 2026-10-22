"""Print the scoreboard of one run: per fault, which detector caught it and how fast; deploy alert counts."""
import sys

import pandas as pd

from logpulse import store
from logpulse.eval import live
from logpulse.paths import RUNS

DETS = ["B1_keyword", "B2_error_rate", "B3_health", "deeplog_vanilla", "deeplog_full"]
run = sys.argv[1]
con = store.connect(RUNS / f"{run}.db", readonly=True)
d = live.load(con)
m = live.map_alerts(d["alerts"], d["gt"], d["sessions"])
det = live.detection_table(m, d["gt"], DETS)
tab = det.assign(cell=[f"{t:.1f}s" if ok else "missed" for ok, t in zip(det["detected"], det["ttd"])])
print("\nTime to detect per fault (from injector's start timestamp):")
print(tab.pivot_table(index="type", columns="detector", values="cell", aggfunc="first")[DETS].to_string())
dep = d["gt"][d["gt"]["type"] == "deploy"]
if len(dep):
    s, e = dep["start_ts"].iloc[0], dep["end_ts"].iloc[0]
    a = d["alerts"]
    w = a[(a["ts"] >= s) & (a["ts"] <= e + 10)]
    print(f"\nF7 deploy ({e - s:.0f}s, no real fault): alerts raised")
    for k in ("deeplog_vanilla", "deeplog_full", "B1_keyword"):
        print(f"  {k:<16} {int((w['detector'] == k).sum()):>6}")
    t = pd.read_sql_query("SELECT event_id, status, matched_to, match_score, template FROM templates "
                          "WHERE status != 'known'", con)
    print("\nNew templates and what the semantic matcher did:")
    print(t.to_string(index=False))
lw = live.lines_to_read(con, d["gt"], m, "deeplog_full")
print("\nLines to read per incident (raw window -> attached to alert):")
print(lw.to_string(index=False))
