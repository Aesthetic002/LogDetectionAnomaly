"""Score the recorded live test runs -> results.csv rows + live figures (note 14).

    python scripts/score_live.py                       # test_s*, test_faultfree, test_deploy_s*

Experiments: E8 (live faults per model), E12 (time to detect), E13 (vs conventional
monitoring), E10 demo part (unseen-template policies after the F7 deploy), E11 demo part
(decision rules), E14 (ablation), OVH (overhead).
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd
import torch

from logpulse import store
from logpulse.eval import live
from logpulse.eval.metrics import prf, write_results
from logpulse.eval.plots import AXIS, INK2, SEQ, SERIES, fig, plt, save
from logpulse.models.deeplog import DeepLog, step_stats
from logpulse.online.demo_templates import V1_EQUIVALENT, statement_of
from logpulse.online.replay import as_sessions, build_traces, load_raw, replay
from logpulse.parsing.drain_parser import level_class
from logpulse.paths import ARTIFACTS, FIGURES, RUNS, UNSEEN

DETS = ["B1_keyword", "B2_error_rate", "B3_health", "rf", "deeplog_vanilla", "deeplog_matcher", "deeplog_topp",
        "deeplog_both", "deeplog_full"]
CONVENTIONAL = ["B1_keyword", "B2_error_rate", "B3_health"]
ABLATION = [("deeplog_vanilla", "Vanilla DeepLog", "P1", "topg"), ("deeplog_matcher", "+ matcher", "P4", "topg"),
            ("deeplog_topp", "+ top-p", "P1", "topp"), ("deeplog_both", "+ both", "P4", "topp"),
            ("deeplog_full", "Full (ours, step-wise)", "P4", "topp")]
FAULTS = ["F1", "F2", "F3", "F4", "F5", "F6"]


def runs(prefix):
    return sorted(p.stem for p in RUNS.glob(f"{prefix}*.db"))


def load_run(name):
    con = store.connect(RUNS / f"{name}.db", readonly=True)
    d = live.load(con)
    d["mapped"] = live.map_alerts(d["alerts"], d["gt"], d["sessions"])
    d["con"] = con
    d["name"] = name
    return d


def iqr(x):
    x = np.asarray([v for v in x if not np.isnan(v)])
    return (float(np.percentile(x, 75) - np.percentile(x, 25))) if len(x) else np.nan


def fault_runs(test):
    """Detection rows across all test runs (one row per fault x detector)."""
    det = []
    for d in test:
        t = live.detection_table(d["mapped"], d["gt"], DETS)
        t["run"] = d["name"]
        det.append(t)
    return pd.concat(det, ignore_index=True) if det else pd.DataFrame()


def steady_fa(runs_):
    """False alarms per hour on fault-free periods, pooled over runs (debounced)."""
    tot = {d: [0, 0.0, 0] for d in DETS}
    for d in runs_:
        gt = d["gt"]
        deploy = gt[gt["type"] == "deploy"]
        hi = deploy["start_ts"].min() if len(deploy) else None
        fa = live.false_alarms(d["mapped"], gt, d["t0"], d["t1"], DETS, hi=hi)
        for r in fa.itertuples():
            tot[r.detector][0] += r.fa_debounced
            tot[r.detector][1] += r.hours
            tot[r.detector][2] += r.fa_raw
    return {k: {"fa_per_h": v[0] / v[1] if v[1] else np.nan, "hours": v[1], "fa_raw_per_h": v[2] / v[1] if v[1] else np.nan}
            for k, v in tot.items()}


def deploy_fa(deploys, minutes=30):
    tot = {d: [0, 0.0, 0] for d in DETS}
    for d in deploys:
        dep = d["gt"][d["gt"]["type"] == "deploy"]
        if dep.empty:
            continue
        s = float(dep["start_ts"].iloc[0])
        fa = live.false_alarms(d["mapped"], d["gt"], d["t0"], d["t1"], DETS, lo=s, hi=s + minutes * 60)
        for r in fa.itertuples():
            tot[r.detector][0] += r.fa_debounced
            tot[r.detector][1] += r.hours
            tot[r.detector][2] += r.fa_raw
    return {k: {"fa_per_h": v[0] / v[1] if v[1] else np.nan, "hours": v[1], "fa_raw_per_h": v[2] / v[1] if v[1] else np.nan}
            for k, v in tot.items()}


# ------------------------------------------------------------------ E10 demo: policies P1-P4 by replay

def policy_tokens(raw, templates, policy, tau):
    if policy == "P4":
        return build_traces(raw, templates, tau)
    tr = build_traces(raw, templates, None)
    ev = raw[raw["trace_id"].notna() & (raw["trace_id"] != "-")].sort_values(["trace_id", "ts", "id"], kind="stable")
    seqs = []
    for _, g in ev.groupby("trace_id", sort=False):
        out = []
        for e, lv in zip(g["eid"], g["level"]):
            if templates[e]["known"]:
                out.append(e)
            elif policy == "P1" or (policy == "P3" and level_class(lv) == "error"):
                out.append(UNSEEN)
            # P2 drops every unseen event; P3 drops unseen INFO events
        seqs.append(np.array(out, dtype=np.int64))
    tr["p4"] = seqs
    return tr


def first_bad_ts(raw, traces, st, rule, param, policy, templates, tau):
    """Approximate alert time: timestamp of the first anomalous step's event."""
    flags = st.steps(rule, param)
    bad = st.first_bad(flags)
    ev = raw[raw["trace_id"].notna() & (raw["trace_id"] != "-")].sort_values(["trace_id", "ts", "id"], kind="stable")
    ts_by_trace = {}
    for tid, g in ev.groupby("trace_id", sort=False):
        keep = []
        for t, e, lv in zip(g["ts"], g["eid"], g["level"]):
            tok_kept = templates[e]["known"] or policy == "P1" or (policy == "P3" and level_class(lv) == "error") or \
                (policy == "P4" and ((tau is not None and templates[e].get("best") is not None and
                                      templates[e]["best_score"] >= tau) or level_class(lv) == "error"))
            if tok_kept:
                keep.append(t)
        ts_by_trace[tid] = keep
    rows = []
    for i, tid in enumerate(traces["trace_id"]):
        if bad[i] >= 0:
            ts_list = ts_by_trace[tid]
            rows.append({"detector": policy, "ts": ts_list[min(bad[i], len(ts_list) - 1)], "trace_id": tid,
                         "service": None})
    return pd.DataFrame(rows, columns=["detector", "ts", "trace_id", "service"])


def e10_demo(deploy_names, art, cfg, model, h):
    rows, mapping_rows = [], []
    for name in deploy_names:
        rp = replay(name, art, cfg["tau"])
        _, gt, _ = load_raw(name)
        ses = as_sessions(rp.traces)
        y = live.trace_labels(ses, gt).reindex(rp.traces["trace_id"]).to_numpy()
        dep = gt[gt["type"] == "deploy"]
        s0 = float(dep["start_ts"].iloc[0]) if len(dep) else rp.raw["ts"].min()
        for policy in ["P1", "P2", "P3", "P4"]:
            tr = policy_tokens(rp.raw, rp.templates, policy, cfg["tau"])
            st = step_stats(model, list(tr["p4"]), h)
            pred = st.predict("topg", cfg["g"])
            alerts = first_bad_ts(rp.raw, tr, st, "topg", cfg["g"], policy, rp.templates, cfg["tau"])
            m = live.map_alerts(alerts, gt, ses)
            fa = live.false_alarms(m, gt, rp.raw["ts"].min(), rp.raw["ts"].max(), [policy], lo=s0, hi=s0 + 1800)
            det = live.detection_table(m, gt, [policy])
            rows.append({"run": name, "policy": policy, **prf(y, pred),
                         "fa_per_h": fa["fa_per_h"].iloc[0], "fa_raw_per_h": fa["fa_raw_per_h"].iloc[0],
                         "fault_recall": det["detected"].mean() if len(det) else np.nan})
        # mapping correctness — computed from the known v1 <-> v2 statement pairs
        stmt_of_eid = rp.raw.groupby("eid")["msg"].agg(lambda m: statement_of(m.iloc[0])).to_dict()
        for e, t in rp.templates.items():
            if t["known"] or t["service"] != "payment":
                continue
            sid = stmt_of_eid.get(e, "?")
            mapped = t.get("best") if t.get("best_score", 0) >= cfg["tau"] else None
            target = V1_EQUIVALENT.get(sid)
            correct = (mapped is None) if target is None else (mapped is not None and stmt_of_eid.get(mapped) == target)
            mapping_rows.append({"run": name, "novel_template": t["template"], "statement": sid, "level": t["level"],
                                 "mapped_to": mapped, "mapped_template": rp.templates.get(mapped, {}).get("template"),
                                 "similarity": round(t.get("best_score", 0), 3), "expected": target or "unmatched",
                                 "correct": bool(correct)})
    return pd.DataFrame(rows), pd.DataFrame(mapping_rows)


def e11_demo(test_names, art, cfg, model, h):
    seqs, ys = [], []
    for name in test_names:
        rp = replay(name, art, None)
        _, gt, _ = load_raw(name)
        seqs += list(rp.traces["p1"])
        ys.append(live.trace_labels(as_sessions(rp.traces), gt).reindex(rp.traces["trace_id"]).to_numpy())
    y = np.concatenate(ys)
    st = step_stats(model, seqs, h)
    return {rule: prf(y, st.predict(rule, cfg[key])) | {"param": cfg[key]}
            for rule, key in (("topg", "g"), ("topp", "p"), ("surprise", "theta"))}, int(y.sum()), len(y)


# ------------------------------------------------------------------ figures

def fig_table_a(tab):
    dets = ["B1_keyword", "B2_error_rate", "B3_health", "rf", "deeplog_vanilla", "deeplog_full"]
    labels = ["B1 keyword", "B2 error-rate", "B3 health", "RF", "Vanilla\nDeepLog", "Ours\n(step-wise)"]
    M = np.array([[tab.get((f, d), (np.nan,))[0] for d in dets] for f in FAULTS])
    f, ax = fig(7.2, 3.8)
    cmap = plt.matplotlib.colors.ListedColormap(SEQ)
    ax.imshow(M, cmap=cmap, vmin=0, vmax=1, aspect="auto")
    names = {"F1": "F1 payment slow", "F2": "F2 payment down", "F3": "F3 stock step skipped (silent)",
             "F4": "F4 retry storm (silent)", "F5": "F5 DB exhaustion", "F6": "F6 inventory paused"}
    for (i, j), v in np.ndenumerate(M):
        if not np.isnan(v):
            ttd = tab.get((FAULTS[i], dets[j]), (np.nan, np.nan))[1]
            txt = f"{v:.0%}" + ("" if np.isnan(ttd) else f"\n{ttd:.1f}s")
            ax.text(j, i, txt, ha="center", va="center", fontsize=8, color="white" if v > 0.6 else "#0b0b0b")
    ax.set_xticks(range(len(dets)), labels, fontsize=8)
    ax.set_yticks(range(len(FAULTS)), [names[x] for x in FAULTS], fontsize=8)
    ax.grid(False)
    ax.set_title("Detection rate (and median time to detect) per fault — live test runs (E13)")
    save(f, FIGURES / "fig_table_a_heatmap.png")


def fig_ttd(det):
    f, ax = fig(7.2, 3.6)
    dets = [("B1_keyword", "B1 keyword"), ("B2_error_rate", "B2 error-rate"), ("B3_health", "B3 health"),
            ("deeplog_both", "DeepLog session-close"), ("deeplog_full", "Ours step-wise")]
    for k, (d, lab) in enumerate(dets):
        for i, fl in enumerate(FAULTS):
            x = det[(det["detector"] == d) & (det["fault"] == fl) & det["detected"]]["ttd"]
            if len(x):
                med, q1, q3 = np.median(x), np.percentile(x, 25), np.percentile(x, 75)
                y = i + (k - 2) * 0.15
                ax.plot([q1, q3], [y, y], color=SERIES[k], lw=2)
                ax.plot(med, y, "o", color=SERIES[k], ms=6, label=lab if i == 0 or not ax.get_legend_handles_labels()[1].count(lab) else None)
    ax.set_yticks(range(len(FAULTS)), FAULTS)
    ax.set_xscale("symlog", linthresh=1)
    ax.set_xlabel("seconds after fault start (median, IQR whiskers)")
    ax.invert_yaxis()
    h, lab = ax.get_legend_handles_labels()
    uniq = dict(zip(lab, h))
    ax.legend(uniq.values(), uniq.keys(), fontsize=8, loc="lower right")
    ax.set_title("Time to detect per fault type (E12)")
    save(f, FIGURES / "fig_ttd_timeline.png")


def fig_deploy(deploys):
    d = deploys[0]
    dep = d["gt"][d["gt"]["type"] == "deploy"]
    if dep.empty:
        return
    s0 = float(dep["start_ts"].iloc[0])
    a = d["alerts"]
    f, ax = fig(7.2, 3.4)
    for k, (det, lab) in enumerate((("deeplog_vanilla", "Vanilla DeepLog (unseen = anomaly)"),
                                    ("deeplog_full", "Ours (semantic matcher)"))):
        t = (a.loc[a["detector"] == det, "ts"] - s0) / 60
        bins = np.arange(-3, (d["t1"] - s0) / 60 + 1, 0.5)
        cnt, edges = np.histogram(t, bins=bins)
        ax.plot(edges[:-1], cnt * 2, color=SERIES[k], label=lab)
    for fl in live.faults_only(d["gt"]).itertuples():
        ax.axvspan((fl.start_ts - s0) / 60, (fl.end_ts - s0) / 60, color=AXIS, alpha=0.35, lw=0)
        ax.text((fl.start_ts - s0) / 60, ax.get_ylim()[1] * 0.95, fl.type.split("_")[0], fontsize=8, color=INK2)
    ax.axvline(0, color=INK2, ls="--", lw=1)
    ax.text(0.1, ax.get_ylim()[1] * 0.85, "deploy payment:v2", fontsize=8, color=INK2)
    ax.set_xlabel("minutes since deploy")
    ax.set_ylabel("alerts / min")
    ax.set_title("Alerts around the F7 deploy (grey = real faults)")
    ax.legend(fontsize=8, loc="upper right")
    save(f, FIGURES / "fig_deploy_alerts.png")


# ------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--art", default=str(ARTIFACTS / "demo"))
    args = ap.parse_args()
    from pathlib import Path
    art = Path(args.art)
    torch.set_num_threads(2)
    cfg = json.loads((art / "config.json").read_text())
    model, ck = DeepLog.load(art / "deeplog.pt")
    h = ck["h"]

    test = [load_run(n) for n in runs("test_s")]
    free = [load_run(n) for n in runs("test_faultfree")]
    deploys = [load_run(n) for n in runs("test_deploy_s")]
    print("test runs:", [d["name"] for d in test], "fault-free:", [d["name"] for d in free],
          "deploy:", [d["name"] for d in deploys])
    rows = []
    det = fault_runs(test)
    note = "src=live;reduced protocol"

    # Table A / E13 + E8 + E12
    tab = {}
    for (fl, d), g in det.groupby(["fault", "detector"]):
        rate = g["detected"].mean()
        ttd = g.loc[g["detected"], "ttd"]
        tab[(fl, d)] = (rate, float(np.median(ttd)) if len(ttd) else np.nan)
        rows += [{"exp_id": "E13", "dataset": "demo", "split": "test", "model": d, "metric": f"detection_rate@{fl}",
                  "value": rate, "notes": f"{note};runs={len(g)}"},
                 {"exp_id": "E12", "dataset": "demo", "split": "test", "model": d, "metric": f"median_ttd_s@{fl}",
                  "value": tab[(fl, d)][1], "notes": f"{note};detected={int(g['detected'].sum())}/{len(g)}"}]
    for d, g in det.groupby("detector"):
        ttd = g.loc[g["detected"], "ttd"]
        silent = g[g["fault"].isin(live.SILENT)]
        rows += [{"exp_id": "E13", "dataset": "demo", "split": "test", "model": d, "metric": "detection_rate@all",
                  "value": g["detected"].mean(), "notes": f"{note};runs={len(g)}"},
                 {"exp_id": "E13", "dataset": "demo", "split": "test", "model": d, "metric": "detection_rate@silent",
                  "value": silent["detected"].mean() if len(silent) else np.nan, "notes": f"{note};runs={len(silent)}"},
                 {"exp_id": "E12", "dataset": "demo", "split": "test", "model": d, "metric": "median_ttd_s@all",
                  "value": float(np.median(ttd)) if len(ttd) else np.nan, "notes": note},
                 {"exp_id": "E12", "dataset": "demo", "split": "test", "model": d, "metric": "iqr_ttd_s@all",
                  "value": iqr(ttd), "notes": note}]
    fa = steady_fa(test + free)
    for d, v in fa.items():
        rows += [{"exp_id": "E13", "dataset": "demo", "split": "test", "model": d, "metric": "fa_per_h@steady",
                  "value": v["fa_per_h"], "notes": f"{note};debounced 10s;hours={v['hours']:.2f}"},
                 {"exp_id": "E13", "dataset": "demo", "split": "test", "model": d, "metric": "fa_raw_per_h@steady",
                  "value": v["fa_raw_per_h"], "notes": f"{note};raw alerts"}]
    # session-level P/R/F1 per model detector (Table 4 / E8)
    sp = []
    for d in test:
        s = live.session_prf(d["alerts"], d["sessions"], d["gt"], DETS[3:])
        s["run"] = d["name"]
        sp.append(s)
    if sp:
        sp = pd.concat(sp)
        for dname, g in sp.groupby("detector"):
            rows.append({"exp_id": "E8", "dataset": "demo", "split": "test", "model": dname,
                         "precision": g["precision"].mean(), "recall": g["recall"].mean(), "f1": g["f1"].mean(),
                         "notes": f"{note};trace-level, mean over {len(g)} runs"})
    # lines to read (H4)
    ltr = pd.concat([live.lines_to_read(d["con"], d["gt"], d["mapped"], "deeplog_full") for d in test]) if test else pd.DataFrame()
    if len(ltr):
        rows += [{"exp_id": "E13", "dataset": "demo", "split": "test", "model": "deeplog_full",
                  "metric": "lines_in_window_median", "value": float(ltr["lines_in_window"].median()), "notes": note},
                 {"exp_id": "E13", "dataset": "demo", "split": "test", "model": "deeplog_full",
                  "metric": "lines_attached_median", "value": float(ltr["lines_attached"].dropna().median()), "notes": note}]

    # deploy block (E10 demo + E14 FA after deploy)
    if deploys:
        dfa = deploy_fa(deploys)
        for d, v in dfa.items():
            rows.append({"exp_id": "E14", "dataset": "demo", "split": "test", "model": d, "metric": "fa_per_h@after_deploy",
                         "value": v["fa_per_h"], "notes": f"{note};first 30 min after F7;hours={v['hours']:.2f}"})
            rows.append({"exp_id": "E14", "dataset": "demo", "split": "test", "model": d,
                         "metric": "fa_raw_per_h@after_deploy", "value": v["fa_raw_per_h"], "notes": f"{note};raw"})
        ddet = fault_runs(deploys)
        for d, g in ddet.groupby("detector"):
            rows.append({"exp_id": "E14", "dataset": "demo", "split": "test", "model": d,
                         "metric": "fault_recall@after_deploy", "value": g["detected"].mean(),
                         "notes": f"{note};real faults during deploy block;runs={len(g)}"})
        pol, mapping = e10_demo([d["name"] for d in deploys], art, cfg, model, h)
        for p_, g in pol.groupby("policy"):
            rows.append({"exp_id": "E10", "dataset": "demo", "split": "test", "model": f"DeepLog+{p_}",
                         "precision": g["precision"].mean(), "recall": g["recall"].mean(), "f1": g["f1"].mean(),
                         "notes": f"src=demo;policy={p_};tau={cfg['tau']};rule=topg;g={cfg['g']}"})
            rows += [{"exp_id": "E10", "dataset": "demo", "split": "test", "model": f"DeepLog+{p_}", "metric": m,
                      "value": g[m].mean(), "notes": f"src=demo;policy={p_};{note}"}
                     for m in ("fa_per_h", "fa_raw_per_h", "fault_recall")]
        if len(mapping):
            mapping.to_csv(FIGURES.parent / "demo_matcher_mapping.csv", index=False)
            rows.append({"exp_id": "E10", "dataset": "demo", "split": "test", "model": "DeepLog+P4",
                         "metric": "unseen_mapped_correctly", "value": mapping["correct"].mean(),
                         "notes": f"src=demo;n={len(mapping)} novel payment templates"})
        fig_deploy(deploys)

    # E11 demo — decision rules on test-run replays
    if test:
        res, n_anom, n = e11_demo([d["name"] for d in test], art, cfg, model, h)
        for rule, m in res.items():
            rows.append({"exp_id": "E11", "dataset": "demo", "split": "test", "model": f"DeepLog/{rule}",
                         "precision": m["precision"], "recall": m["recall"], "f1": m["f1"],
                         "notes": f"src=demo;param={m['param']};traces={n};anomalous={n_anom}"})

    # overhead (Table E)
    stats = [pd.read_csv(RUNS / f"{d['name']}_stats.csv") for d in test + free + deploys
             if (RUNS / f"{d['name']}_stats.csv").exists()]
    if stats:
        s = pd.concat(stats)
        s["name"] = s["name"].str.replace(r"^logpulse-|-1$", "", regex=True)
        for name, g in s.groupby("name"):
            rows += [{"exp_id": "OVH", "dataset": "demo", "split": "test", "model": name, "metric": "cpu_pct_mean",
                      "value": g["cpu_pct"].mean(), "notes": note},
                     {"exp_id": "OVH", "dataset": "demo", "split": "test", "model": name, "metric": "mem_mb_mean",
                      "value": g["mem_mb"].mean(), "notes": note}]
    thr = []
    for d in test + free + deploys:
        if d["t1"] and d["t0"]:
            thr.append(d["n_lines"] / (d["t1"] - d["t0"]))
        lag = pd.read_sql_query("SELECT a.ts - e.ts AS lag FROM alerts a JOIN events e ON e.raw_id = a.raw_ref "
                                "WHERE a.detector = 'deeplog_full'", d["con"])
        if len(lag):
            rows.append({"exp_id": "OVH", "dataset": "demo", "split": "test", "model": "detector",
                         "metric": f"alert_lag_median_s@{d['name']}", "value": float(lag["lag"].median()),
                         "notes": "alert time - offending log line time (reorder buffer + shipping + scoring)"})
    if thr:
        rows.append({"exp_id": "OVH", "dataset": "demo", "split": "test", "model": "detector",
                     "metric": "lines_per_s_mean", "value": float(np.mean(thr)), "notes": note})

    for exp in ("E8", "E12", "E13", "E14", "OVH"):
        write_results(exp, [r for r in rows if r["exp_id"] == exp], tag="src=live" if exp != "OVH" else None)
    write_results("E10", [r for r in rows if r["exp_id"] == "E10"], tag="src=demo")
    write_results("E11", [r for r in rows if r["exp_id"] == "E11"], tag="src=demo")
    if len(det):
        fig_table_a(tab)
        fig_ttd(det)
    det.to_csv(FIGURES.parent / "live_detection_runs.csv", index=False)
    print("scored", len(rows), "rows")


if __name__ == "__main__":
    main()
