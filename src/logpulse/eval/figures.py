"""Report figures — built only from reports/results.csv and data/processed (note 07 'Figures')."""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from logpulse.eval.plots import AXIS, INK2, MUTED, SEQ, SERIES, fig, plt, save
from logpulse.paths import FIGURES, NOVEL_BASE, PROCESSED, RESULTS_CSV

MODELS = ["LR", "DT", "NB", "RF", "PCA", "IsoForest", "DeepLog"]
DS_COLOR = {"hdfs": SERIES[0], "bgl": SERIES[1]}


def _res() -> pd.DataFrame:
    return pd.read_csv(RESULTS_CSV) if RESULTS_CSV.exists() else pd.DataFrame()


def _curve(df, pattern):
    """Rows whose metric matches e.g. r'f1_test@g=(\\d+)' -> sorted (x, value)."""
    out = []
    for m, v in zip(df["metric"], df["value"]):
        mm = re.fullmatch(pattern, str(m))
        if mm:
            out.append((float(mm.group(1)), float(v)))
    return sorted(out)


def ga_vs_simth(r):
    d = r[(r["exp_id"] == "E1") & (r["metric"] == "ga")].copy()
    if d.empty:
        return
    d["sim_th"] = d["notes"].str.extract(r"sim_th=([\d.]+)").astype(float)
    d["masking"] = d["notes"].str.contains("masking=True")
    f, ax = fig(6.4, 3.6)
    for i, ds in enumerate(["HDFS-2k", "BGL-2k"]):
        for mask, ls in ((True, "-"), (False, "--")):
            s = d[(d["dataset"] == ds) & (d["masking"] == mask)].sort_values("sim_th")
            ax.plot(s["sim_th"], s["value"].astype(float), ls, marker="o", color=SERIES[i],
                    label=f"{ds}, {'with' if mask else 'no'} masking")
    ax.set_xlabel("Drain similarity threshold (sim_th)")
    ax.set_ylabel("Grouping accuracy")
    ax.set_ylim(0, 1.02)
    ax.set_title("Parsing accuracy vs sim_th (E1)")
    ax.legend(loc="lower left")
    save(f, FIGURES / "fig_ga_vs_simth.png")


def f1_models(r):
    d = r[(r["exp_id"] == "E2") & r["f1"].notna()]
    if d.empty:
        return
    g = d.groupby(["dataset", "model"])["f1"].agg(["mean", "std"]).reset_index()
    f, ax = fig(7.2, 3.6)
    x = np.arange(len(MODELS))
    w = 0.38
    for i, ds in enumerate(["hdfs", "bgl"]):
        s = g[g["dataset"] == ds].set_index("model").reindex(MODELS)
        bars = ax.bar(x + (i - 0.5) * w, s["mean"], w - 0.03, yerr=s["std"].fillna(0), color=DS_COLOR[ds],
                      label=ds.upper(), error_kw={"ecolor": INK2, "elinewidth": 1, "capsize": 2})
        for b, v in zip(bars, s["mean"]):
            if not np.isnan(v):
                ax.text(b.get_x() + b.get_width() / 2, v + 0.02, f"{v:.2f}", ha="center", fontsize=7, color=INK2)
    ax.set_xticks(x, MODELS)
    ax.set_ylim(0, 1.1)
    ax.set_ylabel("F1 (test, mean ± std over seeds)")
    ax.set_title("Main comparison, chronological split (E2)")
    ax.legend(loc="upper left", ncol=2)
    save(f, FIGURES / "fig_f1_models.png")


def random_vs_chrono(r):
    d = r[(r["exp_id"] == "E3") & r["f1"].notna()]
    if d.empty:
        return
    f, axes = plt.subplots(1, 2, figsize=(8, 3.8), sharey=True)
    for ax, ds in zip(axes, ["hdfs", "bgl"]):
        s = d[d["dataset"] == ds].pivot_table(index="model", columns="split", values="f1")
        for m in s.index:
            hi = m == "DeepLog"
            ax.plot([0, 1], [s.loc[m, "random"], s.loc[m, "chrono"]], marker="o",
                    color=SERIES[1] if hi else AXIS, lw=2.5 if hi else 1.5, zorder=3 if hi else 2)
            ax.text(1.04, s.loc[m, "chrono"], m, va="center", fontsize=8, color=INK2)
        ax.set_xticks([0, 1], ["random split", "chronological"])
        ax.set_xlim(-0.15, 1.45)
        ax.set_title(ds.upper())
    axes[0].set_ylabel("F1 (test)")
    f.suptitle("Random vs chronological split, same parse (E3)", x=0.01, ha="left", fontweight="semibold")
    save(f, FIGURES / "fig_random_vs_chrono.png")


def deeplog_vs_g(r):
    d = r[(r["exp_id"] == "E2") & (r["model"] == "DeepLog") & r["metric"].notna()]
    if d.empty:
        return
    f, axes = plt.subplots(1, 2, figsize=(8, 3.4), sharey=True)
    for ax, ds in zip(axes, ["hdfs", "bgl"]):
        s = d[d["dataset"] == ds]
        for i, k in enumerate(["precision", "recall", "f1"]):
            c = _curve(s, rf"{k}_test@g=(\d+)")
            if c:
                ax.plot(*zip(*c), marker="o", ms=3, color=SERIES[i], label=k)
        ax.set_title(ds.upper())
        ax.set_xlabel("g (top-g acceptance set)")
    axes[0].set_ylabel("test score")
    axes[0].legend(loc="lower right")
    f.suptitle("DeepLog sensitivity to g (E5)", x=0.01, ha="left", fontweight="semibold")
    save(f, FIGURES / "fig_deeplog_vs_g.png")


def topp_vs_p(r):
    d = r[(r["exp_id"] == "E11") & r["metric"].notna()]
    best = r[(r["exp_id"] == "E11") & r["f1"].notna()]
    if d.empty:
        return
    f, axes = plt.subplots(1, 2, figsize=(8, 3.4), sharey=True)
    for ax, ds in zip(axes, ["hdfs", "bgl"]):
        c = _curve(d[d["dataset"] == ds], r"f1_test@p=([\d.]+)")
        if c:
            xs, ys = zip(*c)
            ax.plot(range(len(xs)), ys, marker="o", color=SERIES[0], label="top-p (ours)")
            ax.set_xticks(range(len(xs)), [str(x) for x in xs], rotation=30, fontsize=8)
        g = best[(best["dataset"] == ds) & (best["model"] == "DeepLog/topg") & (best["seed"] == 0)]
        if len(g):
            ax.axhline(g["f1"].iloc[0], color=SERIES[1], ls="--", lw=1.5, label="best top-g (val-tuned)")
        ax.set_title(ds.upper())
        ax.set_xlabel("p (cumulative probability mass)")
    axes[0].set_ylabel("F1 (test)")
    axes[0].legend(loc="lower left")
    f.suptitle("Adaptive top-p vs fixed top-g (E11)", x=0.01, ha="left", fontweight="semibold")
    save(f, FIGURES / "fig_topp_vs_p.png")


def rules_bar(r):
    d = r[(r["exp_id"] == "E11") & r["f1"].notna()]
    if d.empty:
        return
    g = d.groupby(["dataset", "model"])["f1"].agg(["mean", "std"]).reset_index()
    rules = ["DeepLog/topg", "DeepLog/topp", "DeepLog/surprise"]
    labels = ["fixed top-g", "top-p (ours)", "surprise θ"]
    f, ax = fig(6.4, 3.4)
    x = np.arange(2)
    w = 0.26
    for i, (rule, lab) in enumerate(zip(rules, labels)):
        s = g[g["model"] == rule].set_index("dataset").reindex(["hdfs", "bgl"])
        ax.bar(x + (i - 1) * w, s["mean"], w - 0.03, yerr=s["std"].fillna(0), color=SERIES[i], label=lab,
               error_kw={"ecolor": INK2, "elinewidth": 1, "capsize": 2})
    ax.set_xticks(x, ["HDFS", "BGL"])
    ax.set_ylim(0, 1.1)
    ax.set_ylabel("F1 (test)")
    ax.set_title("Decision rule, same trained LSTM (E11)")
    ax.legend(loc="upper right", ncol=3, fontsize=8)
    save(f, FIGURES / "fig_rules.png")


def dt_overfit(r):
    for ds in ["hdfs", "bgl"]:
        d = r[(r["exp_id"] == "E2") & (r["model"] == "DT") & (r["dataset"] == ds) & r["metric"].notna()]
        tr = _curve(d.assign(metric=d["metric"].str.replace("None", "99")), r"f1_train@depth=(\d+)")
        va = _curve(d.assign(metric=d["metric"].str.replace("None", "99")), r"f1_val@depth=(\d+)")
        if not tr:
            continue
        f, ax = fig(5.2, 3.2)
        ax.plot(*zip(*tr), marker="o", color=SERIES[0], label="train")
        ax.plot(*zip(*va), marker="o", color=SERIES[1], label="validation")
        ax.set_xlabel("max depth (99 = unlimited)")
        ax.set_ylabel("F1")
        ax.set_title(f"Decision tree depth vs F1 — {ds.upper()}")
        ax.legend()
        save(f, FIGURES / f"fig_dt_overfit_{ds}.png")


def confusion(r):
    d = r[(r["exp_id"] == "E2") & r["metric"].fillna("").str.startswith("confusion_")]
    if d.empty:
        return
    f, axes = plt.subplots(2, 2, figsize=(6.4, 5.6))
    for row, ds in enumerate(["hdfs", "bgl"]):
        for col, m in enumerate(["RF", "DeepLog"]):
            ax = axes[row, col]
            s = d[(d["dataset"] == ds) & (d["model"] == m)].set_index("metric")["value"].astype(float)
            if s.empty:
                ax.axis("off")
                continue
            M = np.array([[s["confusion_tn"], s["confusion_fp"]], [s["confusion_fn"], s["confusion_tp"]]])
            ax.imshow(np.log10(M + 1), cmap=plt.matplotlib.colors.ListedColormap(SEQ), vmin=0)
            for (i, j), v in np.ndenumerate(M):
                ax.text(j, i, f"{int(v):,}", ha="center", va="center", fontsize=9,
                        color="white" if np.log10(v + 1) > np.log10(M.max() + 1) * 0.55 else "#0b0b0b")
            ax.set_xticks([0, 1], ["pred normal", "pred anomaly"], fontsize=8)
            ax.set_yticks([0, 1], ["normal", "anomaly"], fontsize=8)
            ax.grid(False)
            ax.set_title(f"{m} — {ds.upper()}", fontsize=10)
    f.suptitle("Confusion matrices, chronological test set", x=0.01, ha="left", fontweight="semibold")
    save(f, FIGURES / "fig_confusion.png")


def train_size(r):
    d = r[(r["exp_id"] == "E4") & r["f1"].notna()].copy()
    if d.empty:
        return
    d["frac"] = d["notes"].str.extract(r"train_frac=([\d.]+)").astype(float)
    f, axes = plt.subplots(1, 2, figsize=(8, 3.2), sharey=True)
    for ax, ds in zip(axes, ["hdfs", "bgl"]):
        for i, m in enumerate(["RF", "DeepLog"]):
            s = d[(d["dataset"] == ds) & (d["model"] == m)].sort_values("frac")
            ax.plot(s["frac"] * 100, s["f1"], marker="o", color=SERIES[i], label=m)
        ax.set_xscale("log")
        ax.set_xlabel("% of training data")
        ax.set_title(ds.upper())
    axes[0].set_ylabel("F1 (test)")
    axes[0].legend()
    f.suptitle("Training-set size (E4)", x=0.01, ha="left", fontweight="semibold")
    save(f, FIGURES / "fig_train_size.png")


def policies(r):
    d = r[(r["exp_id"] == "E10") & r["f1"].notna() & r["notes"].fillna("").str.contains("src=bgl")
          & r["notes"].fillna("").str.contains("rule=topg")].copy()
    if d.empty:
        return
    d["tau"] = d["notes"].str.extract(r"tau=([\d.\-]+)")[0]
    f, axes = plt.subplots(1, 2, figsize=(8.4, 3.2), gridspec_kw={"width_ratios": [1.3, 1]})
    base = d[d["tau"].isin(["-", "0.6"])].drop_duplicates("model").set_index("model")
    names = ["DeepLog+P1", "DeepLog+P2", "DeepLog+P3", "DeepLog+P4"]
    labels = ["P1 vanilla", "P2 ignore", "P3 severity", "P4 matcher\n(ours)"]
    vals = [base["f1"].get(n, np.nan) for n in names]
    bars = axes[0].bar(range(4), vals, color=[AXIS, AXIS, AXIS, SERIES[0]])
    for b, v in zip(bars, vals):
        axes[0].text(b.get_x() + b.get_width() / 2, v + 0.01, f"{v:.3f}", ha="center", fontsize=8, color=INK2)
    axes[0].set_xticks(range(4), labels, fontsize=8)
    axes[0].set_ylabel("F1 (BGL test, chrono)")
    axes[0].set_title("Unseen-template policy (E6/E10)")
    p4 = d[d["model"] == "DeepLog+P4"].copy()
    p4["t"] = p4["tau"].astype(float)
    p4 = p4.sort_values("t")
    axes[1].plot(p4["t"], p4["f1"], marker="o", color=SERIES[0])
    axes[1].set_xlabel("matcher threshold τ")
    axes[1].set_title("P4 sensitivity to τ")
    save(f, FIGURES / "fig_policies_bgl.png")


# ------------------------------------------------------------------ EDA (from processed data)

def eda():
    from logpulse.features.sessionize import load_hdfs
    from logpulse.features.windows import load_bgl_lines
    h = load_hdfs("full")
    t = pd.to_datetime(h.time_key, unit="s")
    df = pd.DataFrame({"t": t, "y": h.labels, "n": [len(s) for s in h.seqs]})
    hourly = df.set_index("t").resample("1h")["y"].agg(["count", "sum"])
    f, ax = fig(7.2, 3.2)
    ax.fill_between(hourly.index, hourly["count"], step="mid", color=SERIES[0], alpha=0.25, lw=0, label="sessions")
    ax.plot(hourly.index, hourly["sum"] * 10, color=SERIES[1], lw=1.2, label="anomalous sessions × 10")
    cut = np.sort(h.time_key)[int(0.8 * len(h.time_key))]
    ax.axvline(pd.to_datetime(cut, unit="s"), color=INK2, ls="--", lw=1)
    ax.text(pd.to_datetime(cut, unit="s"), ax.get_ylim()[1] * 0.92, " test →", color=INK2, fontsize=8)
    ax.set_title("HDFS: sessions per hour (chronological split marked)")
    ax.legend(loc="upper left")
    save(f, FIGURES / "fig_eda_hdfs_time.png")

    f, ax = fig(6, 3.2)
    bins = np.arange(0, 60, 1)
    ax.hist(df.loc[df.y == 0, "n"], bins=bins, color=SERIES[0], alpha=0.7, density=True, label="normal")
    ax.hist(df.loc[df.y == 1, "n"], bins=bins, color=SERIES[1], alpha=0.7, density=True, label="anomalous")
    ax.set_xlabel("events per session")
    ax.set_ylabel("share of sessions")
    ax.set_title("HDFS: session length, normal vs anomalous")
    ax.legend()
    save(f, FIGURES / "fig_eda_hdfs_lengths.png")

    lines = load_bgl_lines()
    day = pd.to_datetime(lines["ts"], unit="s").dt.floor("D")
    daily = pd.DataFrame({"d": day, "a": lines["is_anom"]}).groupby("d")["a"].agg(["count", "sum"])
    f, ax = fig(7.2, 3.2)
    ax.bar(daily.index, daily["count"], width=1, color=SERIES[0], alpha=0.35, label="lines/day")
    ax.bar(daily.index, daily["sum"], width=1, color=SERIES[1], label="alert lines/day")
    ax.set_yscale("log")
    ax.set_title("BGL: lines and alert lines per day")
    ax.legend(loc="upper right")
    save(f, FIGURES / "fig_eda_bgl_time.png")

    f, axes = plt.subplots(1, 2, figsize=(8, 3.2))
    for ax, ds in zip(axes, ["hdfs", "bgl"]):
        tpl = pd.read_csv(PROCESSED / ds / "templates_full.csv").sort_values("Occurrences", ascending=False)
        ax.bar(range(len(tpl)), tpl["Occurrences"], color=DS_COLOR[ds], width=1.0)
        ax.set_yscale("log")
        ax.set_xlabel("template rank")
        ax.set_title(f"{ds.upper()}: {len(tpl)} templates")
    axes[0].set_ylabel("occurrences (log)")
    f.suptitle("Template frequency long tail", x=0.01, ha="left", fontweight="semibold")
    save(f, FIGURES / "fig_template_longtail.png")

    cats = lines.loc[lines["is_anom"] == 1, "label"].value_counts().head(12)
    f, ax = fig(6, 3.4)
    ax.barh(cats.index.astype(str)[::-1], cats.values[::-1], color=SERIES[1])
    ax.set_xscale("log")
    ax.set_title("BGL: alert categories (top 12)")
    save(f, FIGURES / "fig_eda_bgl_categories.png")

    th = pd.read_csv(PROCESSED / "bgl" / "templates_honest.csv")
    novel = th[th["EventId"] >= NOVEL_BASE]
    print(f"[EDA] BGL templates only in test period: {len(novel)} covering {novel['Occurrences'].sum():,} lines")


def make_all():
    r = _res()
    for fn in (ga_vs_simth, f1_models, random_vs_chrono, deeplog_vs_g, topp_vs_p, rules_bar, dt_overfit,
               confusion, train_size, policies):
        try:
            fn(r)
        except Exception as e:  # one broken figure must not block the rest
            print(f"[figures] {fn.__name__}: {e}")
    try:
        eda()
    except Exception as e:
        print(f"[figures] eda: {e}")
    print(f"[figures] -> {FIGURES}")
