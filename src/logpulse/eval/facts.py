"""Headline sentences with numbers pulled from results.csv -> reports/facts.json (used by the
report and README). Nothing here is typed by hand."""
from __future__ import annotations

import json
import os
import platform

import numpy as np
import pandas as pd

from logpulse.paths import ARTIFACTS, REPORTS, RESULTS_CSV, RUNS


def _m(r, exp, model, metric, dataset=None):
    q = (r["exp_id"] == exp) & (r["model"] == model) & (r["metric"] == metric)
    if dataset:
        q &= r["dataset"] == dataset
    v = r[q]["value"]
    return float(v.iloc[0]) if len(v) else np.nan


def _f1(r, exp, model, dataset, extra=None):
    q = (r["exp_id"] == exp) & (r["model"] == model) & (r["dataset"] == dataset) & r["f1"].notna()
    if extra:
        q &= r["notes"].fillna("").str.contains(extra, regex=False)
    v = r[q]["f1"]
    return float(v.mean()) if len(v) else np.nan


def build() -> dict:
    r = pd.read_csv(RESULTS_CSV)
    cfg = json.loads((ARTIFACTS / "demo" / "config.json").read_text()) if (ARTIFACTS / "demo" / "config.json").exists() else {}
    f = {}
    ga_h = r[(r["exp_id"] == "E1") & (r["dataset"] == "HDFS-2k") & (r["metric"] == "ga") &
             r["notes"].str.contains("sim_th=0.5;masking=True")]["value"]
    ga_b = r[(r["exp_id"] == "E1") & (r["dataset"] == "BGL-2k") & (r["metric"] == "ga") &
             r["notes"].str.contains("sim_th=0.5;masking=True")]["value"]
    f["ga_hdfs"], f["ga_bgl"] = (float(ga_h.iloc[0]) if len(ga_h) else np.nan), (float(ga_b.iloc[0]) if len(ga_b) else np.nan)
    for ds in ("hdfs", "bgl"):
        for m in ("RF", "DeepLog", "LR", "PCA"):
            f[f"f1_{ds}_{m}"] = _f1(r, "E2", m, ds)
        for rule in ("topg", "topp", "surprise"):
            f[f"e11_{ds}_{rule}"] = _f1(r, "E11", f"DeepLog/{rule}", ds)
        e3 = r[(r["exp_id"] == "E3") & (r["dataset"] == ds) & (r["model"] == "DeepLog")].set_index("split")["f1"]
        if "random" in e3 and "chrono" in e3:
            f[f"e3_{ds}_deeplog"] = (float(e3["random"]), float(e3["chrono"]))
    f["e5b_hdfs"] = _f1(r, "E5b", "DeepLog+EOS/topg", "hdfs")
    for det in ("deeplog_full", "deeplog_vanilla", "B1_keyword", "B2_error_rate", "B3_health", "rf"):
        f[f"det_all_{det}"] = _m(r, "E13", det, "detection_rate@all")
        f[f"det_silent_{det}"] = _m(r, "E13", det, "detection_rate@silent")
        f[f"ttd_{det}"] = _m(r, "E12", det, "median_ttd_s@all")
        f[f"fa_steady_{det}"] = _m(r, "E13", det, "fa_per_h@steady")
        f[f"fa_deploy_{det}"] = _m(r, "E14", det, "fa_per_h@after_deploy")
        f[f"fa_deploy_raw_{det}"] = _m(r, "E14", det, "fa_raw_per_h@after_deploy")
        f[f"recall_deploy_{det}"] = _m(r, "E14", det, "fault_recall@after_deploy")
    f["ttd_deeplog_both"] = _m(r, "E12", "deeplog_both", "median_ttd_s@all")
    f["lines_window"] = _m(r, "E13", "deeplog_full", "lines_in_window_median")
    f["lines_attached"] = _m(r, "E13", "deeplog_full", "lines_attached_median")
    f["mapped_correct"] = _m(r, "E10", "DeepLog+P4", "unseen_mapped_correctly")
    f["cfg"] = cfg
    runs = sorted(p.stem for p in RUNS.glob("test_*.db"))
    f["test_runs"] = runs

    def pct(x):
        return "n/a" if np.isnan(x) else f"{x:.0%}"

    def num(x, nd=3):
        return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{nd}f}"

    conv = {k: f[f"det_silent_{k}"] for k in ("B1_keyword", "B2_error_rate", "B3_health")}
    best_conv_silent = max(conv.values()) if conv else np.nan
    f["abstract"] = " ".join(f"""
Modern applications are built as many cooperating microservices, each producing large volumes of unstructured log
messages; failures are often visible in the logs long before users report them, but the volume makes manual inspection
impractical and keyword-based alerting misses failures that produce no explicit error. This project builds an
end-to-end log anomaly detection pipeline: raw messages are converted into event templates with the Drain online
parser, grouped into sessions by block identifier (HDFS), fixed windows (BGL) or propagated trace identifier
(microservices), and analysed with classical models (Logistic Regression, Decision Tree, Naive Bayes, Random Forest,
PCA, Isolation Forest) and a DeepLog-style LSTM trained only on normal data. Drain reaches a grouping accuracy of
{num(f['ga_hdfs'])} on HDFS-2k and {num(f['ga_bgl'])} on BGL-2k. Under a leakage-free chronological split, with the
parser fitted on the training period only, Random Forest reaches F1 {num(f['f1_hdfs_RF'])} on HDFS and
{num(f['f1_bgl_RF'])} on BGL, while DeepLog reaches {num(f['f1_hdfs_DeepLog'])} and {num(f['f1_bgl_DeepLog'])} —
BGL's many templates that only appear later in time are the main difficulty. On top of DeepLog we add a semantic
template matcher for reworded log messages, an adaptive top-p acceptance rule and step-wise online scoring, and run the
system live on a four-service application with seven injected fault types next to keyword, error-rate and
health-check alerting. In the live test runs our detector caught {pct(f['det_all_deeplog_full'])} of injected faults
and {pct(f['det_silent_deeplog_full'])} of silent faults (best conventional method: {pct(best_conv_silent)}), with a
median time to detect of {num(f['ttd_deeplog_full'], 1)} s, and after a deployment that reworded payment-service
messages the matcher reduced debounced false alarms from {num(f['fa_deploy_deeplog_vanilla'], 1)}/h (vanilla DeepLog)
to {num(f['fa_deploy_deeplog_full'], 1)}/h.""".split())
    f["hardware"] = (f"{platform.system()} {platform.release()} laptop, {os.cpu_count()} logical CPUs, 15.7 GB RAM, "
                     "no GPU; Docker Desktop 28 (WSL2 backend)")
    f["protocol"] = " ".join(f"""
Benchmarks: three seeds for every classical model and for DeepLog in the main comparison (E2, E11); one seed for
E3–E5, E7 and the window variants (the specified protocol is five seeds). Live: the demo model was trained on
30+ minutes of healthy traffic at 20 requests/s; detectors were tuned on two tuning schedules (seeds 1–2, faults F1–F6
once each) plus one deploy tuning run (seed 3); reported numbers come from three test schedules (seeds 4–6, each fault
type once per schedule, 75 s ± 20 % faults separated by at least 105 s of normal traffic, i.e. three runs per fault
type), a 20-minute fault-free block and two deploy blocks (seeds 7–8) with F1, F3 and F4 injected after the F7 deploy.
The specified protocol (ten runs per fault type, 2–3 minute faults, two fault-free hours, five 30-minute deploy blocks)
is supported by the same scripts with different flags; all live numbers below are therefore from a reduced protocol
and are reported with their run counts. Tuned values: g = {cfg.get('g')}, p = {cfg.get('p')}, θ = {cfg.get('theta')},
τ = {cfg.get('tau')}, B1 debounce = {cfg.get('b1_debounce')} s, B2 threshold = {cfg.get('b2_threshold')}.""".split())
    (REPORTS / "facts.json").write_text(json.dumps(f, indent=1, default=float), encoding="utf-8")
    return f


if __name__ == "__main__":
    print(json.dumps(build(), indent=1, default=float)[:3000])
