"""Build the time-to-root-cause study kit (note 14, Table F) from recorded test runs.

    python scripts/user_study/make_packs.py --runs test_s4 test_s5 --participants 8

Creates reports/user_study/:
  packs/incident_XX/A_raw_logs.txt     condition A — every raw line from every service in the
                                       fault window (+-60 s), interleaved, like `docker compose logs`
  packs/incident_XX/B_alert_view.md    condition B — our alert drill-down (expected vs observed,
                                       per-step evidence, raw lines of the flagged trace); no verdict
  answer_key.csv                       faulty service + failing step per incident (keep hidden)
  assignment.csv                       participant x incident x condition, counterbalanced, random order
  responses_template.csv               the form the facilitator fills in
"""
from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timezone

import pandas as pd

from logpulse import store
from logpulse.eval import live
from logpulse.paths import REPORTS, RUNS

OUT = REPORTS / "user_study"
STEP = {"F1": "payment charge takes too long (orders times out)", "F2": "payment service unreachable",
        "F3": "stock reservation step skipped by orders", "F4": "payment returns busy repeatedly (retry storm)",
        "F5": "inventory database queries time out", "F6": "inventory does not respond"}


def t(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%H:%M:%S.%f")[:-3]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", required=True)
    ap.add_argument("--participants", type=int, default=8)
    ap.add_argument("--per-participant", type=int, default=3)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    (OUT / "packs").mkdir(parents=True, exist_ok=True)
    key, n = [], 0
    for run in a.runs:
        con = store.connect(RUNS / f"{run}.db", readonly=True)
        d = live.load(con)
        m = live.map_alerts(d["alerts"], d["gt"], d["sessions"])
        for f in live.faults_only(d["gt"]).sort_values("start_ts").itertuples():
            hits = m[(m["fault_id"] == f.fault_id) & (m["detector"] == "deeplog_full")].sort_values("ts")
            if hits.empty:
                continue
            n += 1
            inc = f"incident_{n:02d}"
            p = OUT / "packs" / inc
            p.mkdir(exist_ok=True)
            raw = con.execute("SELECT ts, container, level, trace_id, msg FROM raw_lines WHERE ts BETWEEN ? AND ? "
                              "ORDER BY ts", (f.start_ts - 60, f.end_ts + 30)).fetchall()
            (p / "A_raw_logs.txt").write_text("\n".join(
                f"{r['container']:<22} | {t(r['ts'])} {r['level']:<7} trace={r['trace_id']} {r['msg']}" for r in raw),
                encoding="utf-8")
            al = con.execute("SELECT * FROM alerts WHERE id = ?", (int(hits.iloc[0]["id"]),)).fetchone()
            ev = con.execute("SELECT e.ts, e.service, e.event_id, e.template, r.msg FROM events e JOIN raw_lines r "
                             "ON r.id = e.raw_id WHERE e.trace_id = ? ORDER BY e.ts, e.id", (al["trace_id"],)).fetchall()
            exp = json.loads(al["expected"] or "[]")
            lines = [f"# Alert view — {inc}", "", f"Trace `{al['trace_id']}` · service **{al['service']}** · step {al['step']}",
                     "", "**Model expected next:**", ""]
            lines += [f"- E{e} `{tpl}` (p = {pr:.2f})" for e, pr, tpl in exp[:3]]
            lines += ["", f"**Observed:** E{al['observed']} `{al['observed_template']}` "
                          f"(p = {al['p_observed'] or 0:.3f}) — {al['reason']}", "", "**Trace events:**", "",
                      "| # | time | service | event | raw line |", "|---|---|---|---|---|"]
            lines += [f"| {'**' + str(i) + '**' if i == al['step'] else i} | {t(e['ts'])} | {e['service']} | "
                      f"E{e['event_id']} | {e['msg']} |" for i, e in enumerate(ev)]
            other = hits["service"].value_counts().to_dict()
            lines += ["", f"Other alerts in the same minute by service: {other}"]
            (p / "B_alert_view.md").write_text("\n".join(lines), encoding="utf-8")
            code = f.type.split("_")[0]
            key.append({"incident": inc, "run": run, "fault_id": f.fault_id, "fault": code,
                        "faulty_service": "db/inventory" if code == "F5" else f.target_service,
                        "failing_step": STEP.get(code, "")})
    pd.DataFrame(key).to_csv(OUT / "answer_key.csv", index=False)

    # counterbalanced assignment: each participant sees k incidents, alternating conditions,
    # starting condition alternates across participants; incident order randomised
    incs = [k["incident"] for k in key]
    rows = []
    for pi in range(1, a.participants + 1):
        pick = rng.sample(incs, min(a.per_participant, len(incs)))
        for j, inc in enumerate(pick):
            cond = "AB"[(pi + j) % 2]
            rows.append({"participant": f"P{pi:02d}", "order": j + 1, "incident": inc, "condition": cond,
                         "material": f"packs/{inc}/" + ("A_raw_logs.txt" if cond == "A" else "B_alert_view.md")})
    pd.DataFrame(rows).to_csv(OUT / "assignment.csv", index=False)
    pd.DataFrame([{**r, "start_time": "", "end_time": "", "answer_service": "", "answer_step": "", "notes": ""}
                  for r in rows]).drop(columns=["material"]).to_csv(OUT / "responses_template.csv", index=False)
    print(f"{len(key)} incidents, {len(rows)} sessions -> {OUT}")


if __name__ == "__main__":
    main()
