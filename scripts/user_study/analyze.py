"""Analyse the filled study form -> Table F rows in reports/results.csv (exp USER).

    python scripts/user_study/analyze.py reports/user_study/responses.csv

Times are 'HH:MM:SS'. An answer is correct when the service matches the key (case-insensitive,
'db' and 'inventory' both accepted for F5) and the facilitator marked the step as correct
(answer_step = 'y' / 'yes' / '1'), since the step is free text.
"""
import sys

import numpy as np
import pandas as pd
from scipy.stats import wilcoxon

from logpulse.eval.metrics import write_results
from logpulse.paths import REPORTS


def secs(s):
    h, m, x = (int(v) for v in str(s).split(":"))
    return h * 3600 + m * 60 + x


def main(path):
    r = pd.read_csv(path).dropna(subset=["start_time", "end_time"])
    key = pd.read_csv(REPORTS / "user_study" / "answer_key.csv").set_index("incident")
    r["time_s"] = r["end_time"].map(secs) - r["start_time"].map(secs)
    ok_svc = [str(a).lower() in str(key.loc[i, "faulty_service"]).lower().split("/") for a, i in zip(r["answer_service"], r["incident"])]
    ok_step = r["answer_step"].astype(str).str.lower().isin(["y", "yes", "1", "true"])
    r["correct"] = np.array(ok_svc) & ok_step
    rows = []
    for cond, g in r.groupby("condition"):
        rows += [{"dataset": "user_study", "split": "-", "model": cond, "metric": "median_time_s",
                  "value": g["time_s"].median(), "notes": f"n={len(g)}"},
                 {"dataset": "user_study", "split": "-", "model": cond, "metric": "correct_rate",
                  "value": g["correct"].mean(), "notes": f"n={len(g)}"}]
    per = r.pivot_table(index="participant", columns="condition", values="time_s", aggfunc="median").dropna()
    if len(per) >= 5:
        stat = wilcoxon(per["A"], per["B"])
        rows.append({"dataset": "user_study", "split": "-", "model": "A_vs_B", "metric": "wilcoxon_p",
                     "value": stat.pvalue, "notes": f"paired per participant, n={len(per)}"})
    write_results("USER", rows)
    print(pd.DataFrame(rows))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else REPORTS / "user_study" / "responses.csv")
