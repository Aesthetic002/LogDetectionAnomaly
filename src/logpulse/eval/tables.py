"""Every report table, built only from reports/results.csv -> reports/tables.md.

    python -m logpulse.eval.tables
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from logpulse.paths import ARTIFACTS, REPORTS, RESULTS_CSV


def demo_tau() -> str:
    import json
    cfg = ARTIFACTS / "demo" / "config.json"
    return str(json.loads(cfg.read_text()).get("tau", 0.6)) if cfg.exists() else "0.6"

MODELS = ["LR", "DT", "NB", "RF", "PCA", "IsoForest", "DeepLog"]
LABELS = {"LR": "sup", "DT": "sup", "NB": "sup", "RF": "sup", "PCA": "unsup", "IsoForest": "unsup", "DeepLog": "semi"}
DET_NAME = {"B1_keyword": "B1 keyword", "B2_error_rate": "B2 error-rate", "B3_health": "B3 health", "rf": "RF",
            "deeplog_vanilla": "Vanilla DeepLog", "deeplog_matcher": "+ matcher", "deeplog_topp": "+ top-p",
            "deeplog_both": "+ matcher + top-p", "deeplog_full": "DeepLog (ours, step-wise)"}
FAULT_NAME = {"F1": "F1 payment slow", "F2": "F2 payment down", "F3": "F3 stock step skipped",
              "F4": "F4 retry storm", "F5": "F5 DB exhaustion", "F6": "F6 inventory paused"}
VISIBLE = {"F1": "yes", "F2": "yes", "F3": "**no**", "F4": "partly", "F5": "yes", "F6": "partly"}


def f3(x, nd=3):
    return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{nd}f}"


def ms(series, nd=3):
    s = series.dropna()
    if not len(s):
        return "—"
    return f"{s.mean():.{nd}f}" + (f" ± {s.std():.{nd}f}" if len(s) > 1 else "")


def _metric(r, exp, model, metric):
    v = r[(r["exp_id"] == exp) & (r["model"] == model) & (r["metric"] == metric)]["value"]
    return float(v.iloc[0]) if len(v) else np.nan


def t1(r):
    d = r[(r["exp_id"] == "E1") & (r["metric"] == "ga")].copy()
    if d.empty:
        return None
    d["sim_th"] = d["notes"].str.extract(r"sim_th=([\d.]+)")[0].astype(float)
    d["masking"] = d["notes"].str.contains("masking=True")
    d["found"] = d["notes"].str.extract(r"templates=(\d+)")[0]
    d["true"] = d["notes"].str.extract(r"true=(\d+)")[0]
    d["lps"] = d["notes"].str.extract(r"lps=(\d+)")[0]
    rows = []
    for ds, g in d.groupby("dataset"):
        best = g[g["masking"]].sort_values(["value", "sim_th"], ascending=[False, True]).iloc[0]
        nomask = g[(~g["masking"]) & (g["sim_th"] == best["sim_th"])]
        rows.append({"Dataset": ds, "sim_th (chosen)": best["sim_th"], "GA masked": f3(best["value"]),
                     "GA no masking": f3(nomask["value"].iloc[0]) if len(nomask) else "—",
                     "Templates found": best["found"], "True templates": best["true"],
                     "Lines/s (2k, no cache)": best["lps"] if isinstance(best["lps"], str) else "—"})
    for ds in ("hdfs", "bgl"):
        thr = _metric(r, "E1", "Drain3", "throughput_lines_per_s")
        sub = r[(r["exp_id"] == "E1") & (r["dataset"] == ds)]
        if len(sub):
            g = lambda m: sub[sub["metric"] == m]["value"]  # noqa: E731
            rows.append({"Dataset": f"{ds.upper()} full", "sim_th (chosen)": 0.5, "GA masked": "n/a",
                         "GA no masking": "n/a", "Templates found": int(float(g("templates_full").iloc[0])),
                         "True templates": "—",
                         "Lines/s (2k, no cache)": f"{float(g('throughput_lines_per_s').iloc[0]):,.0f} (full file, cached)"})
    return pd.DataFrame(rows)


def t2(r):
    d = r[(r["exp_id"] == "E2") & r["f1"].notna()]
    if d.empty:
        return None
    rows = []
    for m in MODELS:
        row = {"Model": m, "Labels": LABELS[m]}
        for ds in ("hdfs", "bgl"):
            g = d[(d["model"] == m) & (d["dataset"] == ds)]
            for k, lab in (("precision", "P"), ("recall", "R"), ("f1", "F1")):
                row[f"{ds.upper()} {lab}"] = ms(g[k])
            row[f"{ds.upper()} PR-AUC"] = ms(g["pr_auc"])
        rows.append(row)
    return pd.DataFrame(rows)


def t3(r):
    d = r[(r["exp_id"] == "E3") & r["f1"].notna()]
    if d.empty:
        return None
    rows = []
    for ds in ("hdfs", "bgl"):
        for m in MODELS:
            g = d[(d["model"] == m) & (d["dataset"] == ds)].set_index("split")["f1"]
            if "random" in g and "chrono" in g:
                rows.append({"Model": m, "Dataset": ds.upper(), "F1 random": f3(g["random"]),
                             "F1 chrono": f3(g["chrono"]), "Δ": f"{g['chrono'] - g['random']:+.3f}"})
    return pd.DataFrame(rows)


def t_live_a(r):
    d = r[r["exp_id"] == "E13"]
    if d.empty:
        return None
    dets = ["B1_keyword", "B2_error_rate", "B3_health", "rf", "deeplog_vanilla", "deeplog_full"]
    rows = []
    for fl in list(FAULT_NAME) + ["all", "silent"]:
        row = {"Fault": FAULT_NAME.get(fl, "**All faults**" if fl == "all" else "**Silent faults (F3, F4)**"),
               "Visible error?": VISIBLE.get(fl, "")}
        for det in dets:
            rate = _metric(r, "E13", det, f"detection_rate@{fl}")
            ttd = _metric(r, "E12", det, f"median_ttd_s@{fl}")
            row[DET_NAME[det]] = "—" if np.isnan(rate) else f"{rate:.0%}" + ("" if np.isnan(ttd) else f" / {ttd:.1f}s")
        rows.append(row)
    row = {"Fault": "False alarms / h (steady)", "Visible error?": ""}
    for det in dets:
        row[DET_NAME[det]] = f3(_metric(r, "E13", det, "fa_per_h@steady"), 2)
    rows.append(row)
    return pd.DataFrame(rows)


def t_live_b(r):
    if r[r["exp_id"] == "E13"].empty:
        return None
    conv = ["B1_keyword", "B2_error_rate", "B3_health"]

    def best(metric, fn):
        vals = {c: _metric(r, "E13" if "rate" in metric else "E12", c, metric) for c in conv}
        vals = {k: v for k, v in vals.items() if not np.isnan(v)}
        if not vals:
            return "—", np.nan
        k = fn(vals, key=vals.get)
        return f"{vals[k]:.0%} ({DET_NAME[k]})" if "rate" in metric else f"{vals[k]:.1f} s ({DET_NAME[k]})", vals[k]

    rows = []
    for metric, lab in (("detection_rate@all", "Fault detection rate (all)"),
                        ("detection_rate@silent", "Fault detection rate (silent)")):
        txt, v = best(metric, max)
        ours = _metric(r, "E13", "deeplog_full", metric)
        rows.append({"Metric": lab, "Best conventional": txt, "Ours": f"{ours:.0%}",
                     "Change": "—" if np.isnan(v) else f"{(ours - v) * 100:+.0f} pts"})
    txt, v = best("median_ttd_s@all", min)
    ours = _metric(r, "E12", "deeplog_full", "median_ttd_s@all")
    rows.append({"Metric": "Median time to detect", "Best conventional": txt, "Ours": f"{ours:.1f} s",
                 "Change": "—" if np.isnan(v) or np.isnan(ours) else f"{ours - v:+.1f} s"})
    van = _metric(r, "E14", "deeplog_vanilla", "fa_per_h@after_deploy")
    ours = _metric(r, "E14", "deeplog_full", "fa_per_h@after_deploy")
    rows.append({"Metric": "False alarms / h after deploy (debounced)", "Best conventional": f"{f3(van, 1)} (vanilla DeepLog)",
                 "Ours": f3(ours, 1), "Change": "—" if np.isnan(van) or van == 0 else f"{(ours - van) / van:+.0%}"})
    lw = _metric(r, "E13", "deeplog_full", "lines_in_window_median")
    la = _metric(r, "E13", "deeplog_full", "lines_attached_median")
    rows.append({"Metric": "Lines to read per incident (median)", "Best conventional": f"{lw:,.0f} (raw window)",
                 "Ours": f"{la:,.0f} (alert)", "Change": "—" if np.isnan(lw) or not la else f"÷{lw / la:,.0f}"})
    return pd.DataFrame(rows)


def t4(r):
    d = r[(r["exp_id"] == "E8") & r["f1"].notna()]
    if d.empty:
        return None
    rows = []
    for det in ["rf", "deeplog_vanilla", "deeplog_matcher", "deeplog_topp", "deeplog_both", "deeplog_full"]:
        g = d[d["model"] == det]
        if len(g):
            rows.append({"Model": DET_NAME[det], "Trace P": f3(g["precision"].iloc[0]),
                         "Trace R": f3(g["recall"].iloc[0]), "Trace F1": f3(g["f1"].iloc[0]),
                         "F3 detected": f"{_metric(r, 'E13', det, 'detection_rate@F3'):.0%}",
                         "F4 detected": f"{_metric(r, 'E13', det, 'detection_rate@F4'):.0%}",
                         "Median TTD (s)": f3(_metric(r, "E12", det, "median_ttd_s@all"), 1),
                         "FA/h steady": f3(_metric(r, "E13", det, "fa_per_h@steady"), 2)})
    return pd.DataFrame(rows)


def d1(r):
    d = r[r["exp_id"] == "E10"]
    if d.empty:
        return None
    rows = []
    for p, name in (("P1", "P1 vanilla (unseen = anomaly)"), ("P2", "P2 ignore unseen"), ("P3", "P3 severity only"),
                    ("P4", "**P4 semantic matcher (ours)**")):
        model = f"DeepLog+{p}"
        bgl = d[(d["model"] == model) & d["notes"].fillna("").str.contains("src=bgl") &
                d["notes"].fillna("").str.contains("rule=topg") & d["f1"].notna()]
        if p == "P4" and len(bgl):
            bgl = bgl[bgl["notes"].str.contains(f"tau={demo_tau()};")]
        rows.append({"Policy": name,
                     "FA/h after deploy": f3(_metric(r, "E10", model, "fa_per_h"), 1),
                     "Raw alerts/h after deploy": f3(_metric(r, "E10", model, "fa_raw_per_h"), 0),
                     "Recall on real faults": f3(_metric(r, "E10", model, "fault_recall"), 2),
                     "BGL F1 (chrono)": f3(bgl["f1"].iloc[0]) if len(bgl) else "—",
                     "Unseen mapped correctly": (f"{_metric(r, 'E10', model, 'unseen_mapped_correctly'):.0%}"
                                                 if p == "P4" and not np.isnan(_metric(r, "E10", model, "unseen_mapped_correctly")) else "—")})
    return pd.DataFrame(rows)


def d2(r):
    d = r[(r["exp_id"] == "E11") & r["f1"].notna()]
    if d.empty:
        return None
    rows = []
    for rule, lab in (("topg", "Fixed top-g"), ("topp", "**Adaptive top-p (ours)**"), ("surprise", "Surprise threshold θ")):
        g = d[d["model"] == f"DeepLog/{rule}"]
        row = {"Rule": lab}
        for ds in ("hdfs", "bgl", "demo"):
            s = g[g["dataset"] == ds]
            row[f"{ds.upper()} P / R / F1"] = (f"{s['precision'].mean():.3f} / {s['recall'].mean():.3f} / "
                                               f"{s['f1'].mean():.3f}" + (f" (±{s['f1'].std():.3f})" if len(s) > 1 else "")) if len(s) else "—"
        params = {ds: ",".join(sorted(set(g[g["dataset"] == ds]["notes"].str.extract(r"param=([\d.]+)")[0].dropna())))
                  for ds in ("hdfs", "bgl", "demo")}
        row["Chosen param (val)"] = "; ".join(f"{k}: {v}" for k, v in params.items() if v)
        rows.append(row)
    return pd.DataFrame(rows)


def d3(r):
    d = r[r["exp_id"] == "E12"]
    if d.empty:
        return None
    rows = []
    for det in ["B1_keyword", "B2_error_rate", "B3_health", "deeplog_both", "deeplog_full"]:
        lab = {"deeplog_both": "DeepLog session-close", "deeplog_full": "**DeepLog step-wise (ours)**"}.get(det, DET_NAME[det])
        rows.append({"Method": lab, "Median TTD (s)": f3(_metric(r, "E12", det, "median_ttd_s@all"), 1),
                     "IQR (s)": f3(_metric(r, "E12", det, "iqr_ttd_s@all"), 1),
                     "Detection rate": f"{_metric(r, 'E13', det, 'detection_rate@all'):.0%}"})
    return pd.DataFrame(rows)


def ablation(r):
    if r[r["exp_id"].isin(["E14", "E13"])].empty:
        return None
    e10 = r[(r["exp_id"] == "E10") & r["f1"].notna() & r["notes"].fillna("").str.contains("src=bgl")]
    tau = demo_tau()
    bgl = {
        "deeplog_vanilla": e10[(e10["model"] == "DeepLog+P1") & e10["notes"].str.contains("rule=topg")]["f1"],
        "deeplog_matcher": e10[(e10["model"] == "DeepLog+P4") & e10["notes"].str.contains(f"tau={tau};rule=topg")]["f1"],
        "deeplog_topp": e10[(e10["model"] == "DeepLog+P1") & e10["notes"].str.contains("rule=topp")]["f1"],
        "deeplog_both": e10[(e10["model"] == "DeepLog+P4") & e10["notes"].str.contains(f"tau={tau};rule=topp")]["f1"],
    }
    bgl["deeplog_full"] = bgl["deeplog_both"]  # step-wise changes timing, not the decision
    demo = r[(r["exp_id"] == "E8") & r["f1"].notna()].set_index("model")["f1"]
    rows = []
    for det, m, p, s in (("deeplog_vanilla", "✘", "✘", "✘"), ("deeplog_matcher", "✔", "✘", "✘"),
                         ("deeplog_topp", "✘", "✔", "✘"), ("deeplog_both", "✔", "✔", "✘"), ("deeplog_full", "✔", "✔", "✔")):
        rows.append({"Config": DET_NAME[det], "Matcher": m, "Top-p": p, "Step-wise": s,
                     "FA/h after deploy": f3(_metric(r, "E14", det, "fa_per_h@after_deploy"), 1),
                     "F1 BGL": f3(bgl[det].iloc[0]) if len(bgl[det]) else "—",
                     "F1 demo (trace)": f3(demo.get(det, np.nan)),
                     "Median TTD (s)": f3(_metric(r, "E12", det, "median_ttd_s@all"), 1)})
    return pd.DataFrame(rows)


def t_e(r):
    d = r[r["exp_id"] == "OVH"]
    if d.empty:
        return None
    rows = []
    for name in ("detector", "fluent-bit", "gateway", "orders", "inventory", "payment", "db"):
        cpu = _metric(r, "OVH", name, "cpu_pct_mean")
        mem = _metric(r, "OVH", name, "mem_mb_mean")
        if np.isnan(cpu):
            continue
        rows.append({"Component": name, "CPU % (mean)": f3(cpu, 1), "RAM MB (mean)": f3(mem, 0)})
    lag = d[d["metric"].str.startswith("alert_lag_median_s")]["value"]
    lps = _metric(r, "OVH", "detector", "lines_per_s_mean")
    notes = pd.DataFrame([{"Component": "pipeline throughput (lines/s, mean)", "CPU % (mean)": f3(lps, 0), "RAM MB (mean)": ""},
                          {"Component": "alert lag: alert − offending line (s, median over runs)",
                           "CPU % (mean)": f3(lag.median(), 2) if len(lag) else "—", "RAM MB (mean)": ""}])
    return pd.concat([pd.DataFrame(rows), notes], ignore_index=True)


def supplementary(r):
    out = {}
    d = r[(r["exp_id"] == "E4") & r["f1"].notna()].copy()
    if len(d):
        d["frac"] = d["notes"].str.extract(r"train_frac=([\d.]+)")[0]
        out["E4 — training-set size (F1)"] = d.pivot_table(index=["dataset", "frac"], columns="model", values="f1").round(3).reset_index()
    d = r[(r["exp_id"] == "E5") & r["f1"].notna()].copy()
    if len(d):
        d["h"] = d["notes"].str.extract(r"h=(\d+)")[0]
        d["g"] = d["notes"].str.extract(r"g=(\d+)")[0]
        out["E5 — DeepLog window h (F1, g tuned on val)"] = d[["dataset", "h", "g", "precision", "recall", "f1"]].round(3)
    d = r[(r["exp_id"] == "E5b") & r["f1"].notna()].copy()
    if len(d):
        van = r[(r["exp_id"] == "E11") & (r["dataset"] == "hdfs") & (r["seed"] == 0) & r["f1"].notna()]
        rows = []
        for rule in ("topg", "topp", "surprise"):
            v = van[van["model"] == f"DeepLog/{rule}"]
            e = d[d["model"] == f"DeepLog+EOS/{rule}"]
            if len(e):
                rows.append({"Rule": rule, "Vanilla P / R / F1": (f"{v['precision'].iloc[0]:.3f} / {v['recall'].iloc[0]:.3f} / "
                                                                  f"{v['f1'].iloc[0]:.3f}") if len(v) else "—",
                             "+ end-of-session token P / R / F1": f"{e['precision'].iloc[0]:.3f} / {e['recall'].iloc[0]:.3f} / "
                                                                    f"{e['f1'].iloc[0]:.3f}"})
        out["E5b — HDFS: end-of-session token (seed 0)"] = pd.DataFrame(rows)
    d = r[(r["exp_id"] == "E7") & r["f1"].notna()].copy()
    if len(d):
        d["features"] = d["notes"].str.extract(r"features=([\w+]+)")[0]
        out["E7 — feature ablation (F1)"] = d.pivot_table(index=["dataset", "model"], columns="features", values="f1").round(3).reset_index()
    d = r[(r["exp_id"] == "E2b") & r["f1"].notna()].copy()
    if len(d):
        d["window"] = d["notes"].str.extract(r"window=(\w+)")[0]
        out["E2b — BGL window granularity (F1)"] = d.pivot_table(index="model", columns="window", values="f1").round(3).reset_index()
    return out


def f_user(r):
    d = r[r["exp_id"] == "USER"]
    if d.empty:
        return pd.DataFrame([{"Condition": "Raw logs + grep", "Median time to root cause": "pending study",
                              "Correct answers": "pending study"},
                             {"Condition": "Our alert view", "Median time to root cause": "pending study",
                              "Correct answers": "pending study"}])
    rows = []
    for cond in ("A", "B"):
        rows.append({"Condition": "Raw logs + grep" if cond == "A" else "Our alert view",
                     "Median time to root cause": f3(_metric(r, "USER", cond, "median_time_s"), 0) + " s",
                     "Correct answers": f"{_metric(r, 'USER', cond, 'correct_rate'):.0%}"})
    return pd.DataFrame(rows)


TABLES = [
    ("Table 1 — Parsing (E1)", t1), ("Table 2 — Main results, chronological split (E2)", t2),
    ("Table 3 — Random vs chronological split (E3)", t3), ("Table A — Conventional monitoring vs our model (E13)", t_live_a),
    ("Table B — Headline metrics", t_live_b), ("Table 4 — Live faults per model (E8)", t4),
    ("Table D1 — Unseen-template policies (E6 / E10)", d1), ("Table D2 — Decision rule (E11)", d2),
    ("Table D3 — Detection latency (E12)", d3), ("Ablation (E14)", ablation), ("Table E — Overhead", t_e),
    ("Table F — User study (time to root cause)", f_user),
]


def build() -> dict[str, pd.DataFrame]:
    r = pd.read_csv(RESULTS_CSV)
    out = {}
    for title, fn in TABLES:
        try:
            t = fn(r)
        except Exception as e:  # keep building the rest
            print(f"[tables] {title}: {e}")
            t = None
        if t is not None and len(t):
            out[title] = t
    out.update(supplementary(r))
    return out


def to_markdown(tables: dict) -> str:
    parts = ["# LogPulse — results tables", "",
             "Generated by `python -m logpulse.eval.tables` from `reports/results.csv`. "
             "Live numbers come from a **reduced protocol** (see README).", ""]
    for title, t in tables.items():
        parts += [f"## {title}", "", t.to_markdown(index=False), ""]
    return "\n".join(parts)


def main():
    tables = build()
    (REPORTS / "tables.md").write_text(to_markdown(tables), encoding="utf-8")
    print(f"{len(tables)} tables -> reports/tables.md")


if __name__ == "__main__":
    main()
