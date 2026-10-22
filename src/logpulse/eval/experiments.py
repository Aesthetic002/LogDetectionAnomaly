"""Offline benchmark experiments on HDFS and BGL (note 07, E1-E7, E10, E11).

Every number lands in reports/results.csv. Run through scripts/run_all_experiments.py.
"""
from __future__ import annotations

import json
import time
from functools import lru_cache

import numpy as np
import pandas as pd
import torch

from logpulse.eval.metrics import best_threshold, pr_auc, prf, write_results
from logpulse.eval.splits import chronological, make_split
from logpulse.features.sessionize import SessionSet, load_hdfs
from logpulse.features.vectorize import Featurizer, count_matrix
from logpulse.features.windows import fixed_windows, load_bgl_lines, time_windows
from logpulse.models.baselines import SUPERVISED, IsoForestDetector, PCADetector, make_supervised
from logpulse.models.deeplog import DeepLog, step_stats, train
from logpulse.models.template_matcher import POLICIES, TemplateMatcher, apply_policy
from logpulse.parsing.drain_parser import level_class, parse_2k
from logpulse.paths import ARTIFACTS, NOVEL_BASE, PROCESSED

torch.set_num_threads(2)  # fastest for this small LSTM on CPU (benchmarked)
BENCH = ARTIFACTS / "benchmarks"
G_GRID = list(range(1, 16))
P_GRID = [0.8, 0.9, 0.95, 0.99, 0.995, 0.999, 0.9999]
DT_DEPTHS = [2, 4, 6, 8, 10, 12, 15, 20, None]


# ------------------------------------------------------------------ data

@lru_cache(maxsize=None)
def _bgl_lines():
    return load_bgl_lines()


def vocab_size(dataset: str, mode: str) -> int:
    t = pd.read_csv(PROCESSED / dataset / f"templates_{mode}.csv")
    return int(t.loc[t["EventId"] < NOVEL_BASE, "EventId"].max()) + 1


@lru_cache(maxsize=None)
def load(dataset: str, mode: str = "honest", window: str = "fixed20") -> SessionSet:
    if dataset == "hdfs":
        return load_hdfs(mode)
    lines = _bgl_lines()
    if window.startswith("fixed"):
        return fixed_windows(lines, int(window[5:]), mode)
    return time_windows(lines, 3600, 1800, mode)


# ------------------------------------------------------------------ model runners

def classical(ss: SessionSet, split, V, kind="count", seed=0, models=None, tune_dt=True):
    """Fit every classical model on one split. Returns {model: dict(metrics, pred, score, extra)}."""
    models = models or SUPERVISED + ["PCA", "IsoForest"]
    tr, va, te = split
    X = count_matrix(ss.seqs, V)
    fz = Featurizer(kind).fit(X[tr])
    Xtr, Xva, Xte = fz.transform(X[tr]), fz.transform(X[va]), fz.transform(X[te])
    ytr, yva, yte = ss.labels[tr], ss.labels[va], ss.labels[te]
    out = {}
    for name in models:
        t0 = time.time()
        extra = {}
        if name in SUPERVISED:
            depth = 10
            if name == "DT" and tune_dt:
                curve = []
                for d in DT_DEPTHS:
                    m = make_supervised("DT", seed, d).fit(Xtr, ytr)
                    curve.append((d, prf(ytr, m.predict(Xtr))["f1"], prf(yva, m.predict(Xva))["f1"]))
                depth = max(curve, key=lambda c: c[2])[0]
                extra["dt_curve"], extra["depth"] = curve, depth
            m = make_supervised(name, seed, depth).fit(Xtr, ytr)
            pred = m.predict(Xte)
            score = m.predict_proba(Xte)[:, 1] if hasattr(m, "predict_proba") else None
            extra["model"] = m
        else:
            det = PCADetector().fit(Xtr[ytr == 0]) if name == "PCA" else IsoForestDetector(seed).fit(Xtr)
            thr, _ = best_threshold(yva, det.score(Xva))
            score = det.score(Xte)
            pred = (score >= thr).astype(int)
            extra["threshold"] = thr
            if name == "PCA":
                extra["k"] = det.k
        out[name] = {**prf(yte, pred), "pr_auc": pr_auc(yte, score), "train_time_s": time.time() - t0,
                     "pred": pred, "score": score, "extra": extra}
    return out


def deeplog_fit(ss: SessionSet, split, V, h=10, seed=0, tag="", epochs=30, frac=1.0):
    tr, va, _ = split
    if frac < 1.0:
        rng = np.random.default_rng(seed)
        tr = rng.choice(tr, max(1, int(frac * len(tr))), replace=False)
    normal_tr = [ss.seqs[i] for i in tr if ss.labels[i] == 0]
    normal_va = [ss.seqs[i] for i in va if ss.labels[i] == 0]
    model = DeepLog(V)
    log = train(model, normal_tr, h=h, epochs=epochs, val_seqs=normal_va, seed=seed, verbose=True)
    BENCH.mkdir(parents=True, exist_ok=True)
    model.save(BENCH / f"deeplog_{tag}_h{h}_s{seed}.pt", {"h": h, "epochs": log.epochs})
    return model, log


def eval_rules(st_va, y_va, st_te, y_te):
    """Choose each rule's parameter on validation, evaluate once on test."""
    res = {}
    curves = {}
    for rule, grid in (("topg", G_GRID), ("topp", P_GRID)):
        val = [(q, prf(y_va, st_va.predict(rule, q))["f1"]) for q in grid]
        test = [(q, prf(y_te, st_te.predict(rule, q))) for q in grid]
        best = max(val, key=lambda v: v[1])[0]
        res[rule] = {"param": best, **prf(y_te, st_te.predict(rule, best))}
        curves[rule] = {"val": val, "test": [(q, m) for q, m in test]}
    s = -st_va.logp[np.isfinite(st_va.logp)]
    thetas = np.unique(np.quantile(s, np.linspace(0.5, 0.9999, 60))) if s.size else np.array([5.0])
    val = [(float(t), prf(y_va, st_va.predict("surprise", t))["f1"]) for t in thetas]
    best = max(val, key=lambda v: v[1])[0]
    res["surprise"] = {"param": best, **prf(y_te, st_te.predict("surprise", best))}
    return res, curves


def deeplog_eval(model, ss, split, h):
    _, va, te = split
    st_va = step_stats(model, [ss.seqs[i] for i in va], h)
    st_te = step_stats(model, [ss.seqs[i] for i in te], h)
    return st_va, st_te


def _row(dataset, split, model, seed, m, notes="", **kw):
    return {"dataset": dataset, "split": split, "model": model, "seed": seed, "precision": m.get("precision"),
            "recall": m.get("recall"), "f1": m.get("f1"), "pr_auc": m.get("pr_auc"),
            "train_time_s": m.get("train_time_s"), "notes": notes, **kw}


def _metric(dataset, split, model, seed, metric, value, notes=""):
    return {"dataset": dataset, "split": split, "model": model, "seed": seed, "metric": metric,
            "value": value, "notes": notes}


# ------------------------------------------------------------------ E1 parsing

def e1(cfg):
    rows = []
    for ds in ("HDFS", "BGL"):
        for masking in (True, False):
            for s in cfg["sim_th"]:
                r = parse_2k(ds, s, masking)
                rows.append(_metric(r["dataset"], "-", "Drain3", 0, "ga", r["ga"],
                                    f"sim_th={s};masking={masking};templates={r['templates_found']};"
                                    f"true={r['true_templates']};lps={r['lines_per_sec']:.0f}"))
    for ds in ("hdfs", "bgl"):
        meta = json.loads((PROCESSED / ds / "meta.json").read_text())
        rows.append(_metric(ds, "-", "Drain3", 0, "throughput_lines_per_s", meta["lines_per_sec_end_to_end"],
                            "full dataset, masked-string cache; includes file read + masking"))
        rows.append(_metric(ds, "-", "Drain3", 0, "templates_full", meta["templates_full"]))
        rows.append(_metric(ds, "-", "Drain3", 0, "templates_novel_test", meta["templates_novel_test"],
                            "templates first mined in the chronological test period (honest parse)"))
        rows.append(_metric(ds, "-", "Drain3", 0, "compression_lines_per_template",
                            meta["lines"] / meta["templates_full"]))
    write_results("E1", rows)
    return rows


# ------------------------------------------------------------------ E2 main + DeepLog cache

_STATS: dict = {}


def e2(cfg):
    rows = []
    for ds in cfg["datasets"]:
        ss = load(ds, "honest")
        V = vocab_size(ds, "honest")
        split = chronological(ss.time_key)
        _, va, te = split
        print(f"[E2] {ds}: {len(ss):,} sessions, V={V}, train/val/test = {[len(x) for x in split]}", flush=True)
        for seed in cfg["seeds_classical"]:
            res = classical(ss, split, V, "count", seed, tune_dt=(seed == cfg["seeds_classical"][0]))
            for name, m in res.items():
                rows.append(_row(ds, "chrono", name, seed, m, "parse=honest;features=count"))
                if "dt_curve" in m["extra"]:
                    for d, ftr, fva in m["extra"]["dt_curve"]:
                        rows.append(_metric(ds, "chrono", "DT", seed, f"f1_train@depth={d}", ftr))
                        rows.append(_metric(ds, "chrono", "DT", seed, f"f1_val@depth={d}", fva))
                    rows.append(_metric(ds, "chrono", "DT", seed, "chosen_depth", str(m["extra"]["depth"])))
                    _save_tree(m["extra"]["model"], ds, V)
                if seed == cfg["seeds_classical"][0] and name in ("RF", "LR"):
                    _confusion(rows, ds, name, seed, ss.labels[te], m["pred"])
                if name == "RF" and seed == cfg["seeds_classical"][0]:
                    imp = m["extra"]["model"].feature_importances_
                    for e in np.argsort(imp)[::-1][:10]:
                        rows.append(_metric(ds, "chrono", "RF", seed, f"importance@E{e}", float(imp[e])))
        for seed in cfg["seeds_deeplog"]:
            print(f"[E2] {ds} DeepLog seed {seed}", flush=True)
            model, log = deeplog_fit(ss, split, V, cfg["h"], seed, f"{ds}_honest_chrono")
            st_va, st_te = deeplog_eval(model, ss, split, cfg["h"])
            _STATS[(ds, seed)] = (model, st_va, st_te)
            res, curves = eval_rules(st_va, ss.labels[va], st_te, ss.labels[te])
            g = res["topg"]["param"]
            m = {**res["topg"], "pr_auc": pr_auc(ss.labels[te], st_te.seq_score()), "train_time_s": log.seconds}
            rows.append(_row(ds, "chrono", "DeepLog", seed, m, f"parse=honest;rule=top-g;g={g};h={cfg['h']};"
                                                                  f"epochs={log.epochs};unseen=P1"))
            if seed == cfg["seeds_deeplog"][0]:
                _confusion(rows, ds, "DeepLog", seed, ss.labels[te], st_te.predict("topg", g))
                for q, mm in curves["topg"]["test"]:
                    for k in ("precision", "recall", "f1"):
                        rows.append(_metric(ds, "chrono", "DeepLog", seed, f"{k}_test@g={q}", mm[k], "E5 curve"))
                for q, f in curves["topg"]["val"]:
                    rows.append(_metric(ds, "chrono", "DeepLog", seed, f"f1_val@g={q}", f, "E5 curve"))
    write_results("E2", rows)
    return rows


def _confusion(rows, ds, name, seed, y, pred):
    y, pred = np.asarray(y), np.asarray(pred).astype(int)
    for k, v in {"tp": ((y == 1) & (pred == 1)).sum(), "fp": ((y == 0) & (pred == 1)).sum(),
                 "fn": ((y == 1) & (pred == 0)).sum(), "tn": ((y == 0) & (pred == 0)).sum()}.items():
        rows.append(_metric(ds, "chrono", name, seed, f"confusion_{k}", int(v)))


def _save_tree(model, ds, V):
    from sklearn.tree import plot_tree

    from logpulse.eval.plots import fig, save
    from logpulse.paths import FIGURES
    t = pd.read_csv(PROCESSED / ds / "templates_honest.csv").set_index("EventId")["EventTemplate"]
    names = [("UNSEEN" if i == 1 else f"E{i}: {str(t.get(i, ''))[:28]}") for i in range(V)]
    f, ax = fig(11, 5.5)
    ax.grid(False)
    plot_tree(model, max_depth=2, feature_names=names, class_names=["normal", "anomaly"], filled=False,
              impurity=False, proportion=True, fontsize=7, ax=ax)
    ax.set_title(f"Decision tree, top levels — {ds.upper()} (chronological split)")
    save(f, FIGURES / f"fig_dt_top_{ds}.png")


def _stats(ds, seed, cfg):
    if (ds, seed) not in _STATS:
        ss = load(ds, "honest")
        V = vocab_size(ds, "honest")
        split = chronological(ss.time_key)
        path = BENCH / f"deeplog_{ds}_honest_chrono_h{cfg['h']}_s{seed}.pt"
        if path.exists():
            model, _ = DeepLog.load(path)
        else:
            model, _ = deeplog_fit(ss, split, V, cfg["h"], seed, f"{ds}_honest_chrono")
        _STATS[(ds, seed)] = (model, *deeplog_eval(model, ss, split, cfg["h"]))
    return _STATS[(ds, seed)]


# ------------------------------------------------------------------ E3 random vs chronological

def e3(cfg):
    rows = []
    for ds in cfg["datasets"]:
        ss = load(ds, "full")
        V = vocab_size(ds, "full")
        for kind in ("chrono", "random"):
            split = make_split(kind, ss.time_key, seed=0)
            _, va, te = split
            res = classical(ss, split, V, "count", 0, tune_dt=False)
            for name, m in res.items():
                rows.append(_row(ds, kind, name, 0, m, "parse=full;features=count"))
            model, log = deeplog_fit(ss, split, V, cfg["h"], 0, f"{ds}_full_{kind}")
            st_va, st_te = deeplog_eval(model, ss, split, cfg["h"])
            res, _ = eval_rules(st_va, ss.labels[va], st_te, ss.labels[te])
            rows.append(_row(ds, kind, "DeepLog", 0, {**res["topg"], "train_time_s": log.seconds},
                             f"parse=full;rule=top-g;g={res['topg']['param']}"))
    write_results("E3", rows)
    return rows


# ------------------------------------------------------------------ E4 training-set size

def e4(cfg):
    rows = []
    for ds in cfg["datasets"]:
        ss = load(ds, "honest")
        V = vocab_size(ds, "honest")
        split = chronological(ss.time_key)
        tr, va, te = split
        for frac in cfg["fractions"]:
            rng = np.random.default_rng(0)
            sub = np.sort(rng.choice(tr, max(1, int(frac * len(tr))), replace=False))
            if ss.labels[sub].sum() > 0:
                res = classical(ss, (sub, va, te), V, "count", 0, models=["RF"], tune_dt=False)
                rows.append(_row(ds, "chrono", "RF", 0, res["RF"], f"train_frac={frac}"))
            if frac == 1.0:
                model, st_va, st_te = _stats(ds, cfg["seeds_deeplog"][0], cfg)
            else:
                model, _ = deeplog_fit(ss, split, V, cfg["h"], 0, f"{ds}_frac{frac}", frac=frac)
                st_va, st_te = deeplog_eval(model, ss, split, cfg["h"])
            res, _ = eval_rules(st_va, ss.labels[va], st_te, ss.labels[te])
            rows.append(_row(ds, "chrono", "DeepLog", 0, res["topg"], f"train_frac={frac};g={res['topg']['param']}"))
    write_results("E4", rows)
    return rows


# ------------------------------------------------------------------ E5 h sensitivity

def e5(cfg):
    rows = []
    for ds in cfg["datasets"]:
        ss = load(ds, "honest")
        V = vocab_size(ds, "honest")
        split = chronological(ss.time_key)
        _, va, te = split
        for h in cfg["h_values"]:
            if h == cfg["h"]:
                _, st_va, st_te = _stats(ds, cfg["seeds_deeplog"][0], cfg)
            else:
                model, _ = deeplog_fit(ss, split, V, h, 0, f"{ds}_honest_chrono")
                st_va, st_te = deeplog_eval(model, ss, split, h)
            res, _ = eval_rules(st_va, ss.labels[va], st_te, ss.labels[te])
            rows.append(_row(ds, "chrono", "DeepLog", 0, res["topg"], f"h={h};g={res['topg']['param']}"))
    write_results("E5", rows)
    return rows


# ------------------------------------------------------------------ E7 feature ablation

def e7(cfg):
    rows = []
    for ds in cfg["datasets"]:
        ss = load(ds, "honest")
        V = vocab_size(ds, "honest")
        split = chronological(ss.time_key)
        for kind in ("count", "tfidf", "binary", "count+len"):
            res = classical(ss, split, V, kind, 0, tune_dt=False)
            for name, m in res.items():
                rows.append(_row(ds, "chrono", name, 0, m, f"features={kind}"))
    write_results("E7", rows)
    return rows


# ------------------------------------------------------------------ E2b BGL window granularity

def e2b(cfg):
    rows = []
    for window in ("fixed100", "time3600"):
        ss = load("bgl", "honest", window)
        V = vocab_size("bgl", "honest")
        split = chronological(ss.time_key)
        res = classical(ss, split, V, "count", 0, tune_dt=False)
        for name, m in res.items():
            rows.append(_row("bgl", "chrono", name, 0, m, f"window={window}"))
        if window == "fixed100":
            _, va, te = split
            model, log = deeplog_fit(ss, split, V, cfg["h"], 0, "bgl_fixed100")
            st_va, st_te = deeplog_eval(model, ss, split, cfg["h"])
            r, _ = eval_rules(st_va, ss.labels[va], st_te, ss.labels[te])
            rows.append(_row("bgl", "chrono", "DeepLog", 0, {**r["topg"], "train_time_s": log.seconds},
                             f"window={window};g={r['topg']['param']}"))
    write_results("E2b", rows)
    return rows


# ------------------------------------------------------------------ E11 decision rules

def e11(cfg):
    rows = []
    for ds in cfg["datasets"]:
        ss = load(ds, "honest")
        split = chronological(ss.time_key)
        _, va, te = split
        for seed in cfg["seeds_deeplog"]:
            _, st_va, st_te = _stats(ds, seed, cfg)
            res, curves = eval_rules(st_va, ss.labels[va], st_te, ss.labels[te])
            for rule, m in res.items():
                rows.append(_row(ds, "chrono", f"DeepLog/{rule}", seed, m, f"param={m['param']}"))
            if seed == cfg["seeds_deeplog"][0]:
                for q, mm in curves["topp"]["test"]:
                    for k in ("precision", "recall", "f1"):
                        rows.append(_metric(ds, "chrono", "DeepLog/topp", seed, f"{k}_test@p={q}", mm[k], "E11 curve"))
                for q, f in curves["topp"]["val"]:
                    rows.append(_metric(ds, "chrono", "DeepLog/topp", seed, f"f1_val@p={q}", f, "E11 curve"))
    write_results("E11", rows)
    return rows


# ------------------------------------------------------------------ E6 / E10 unseen-template policies (BGL)

def bgl_matcher_inputs():
    """Known templates with (component, level class) from the training period, and the
    templates of the novel (test-only) events."""
    lines = _bgl_lines()
    t = pd.read_csv(PROCESSED / "bgl" / "templates_honest.csv").set_index("EventId")["EventTemplate"]
    train = lines[lines["eid_honest"] < NOVEL_BASE]
    pairs = train.groupby(["eid_honest", "component", "level"], observed=True).size().reset_index()
    known = sorted({(int(r.eid_honest), t[int(r.eid_honest)], str(r.component), level_class(r.level))
                    for r in pairs.itertuples()})
    return known, t


def e10_bgl(cfg):
    rows = []
    ss = load("bgl", "honest")
    V = vocab_size("bgl", "honest")
    split = chronological(ss.time_key)
    _, va, te = split
    comps = ss.meta["component_names"]
    known, ttext = bgl_matcher_inputs()
    mapping_rows = []
    for seed in cfg["seeds_deeplog"][:1]:
        model, st_va, _ = _stats("bgl", seed, cfg)
        g = max(((q, prf(ss.labels[va], st_va.predict("topg", q))["f1"]) for q in G_GRID), key=lambda v: v[1])[0]
        pp = max(((q, prf(ss.labels[va], st_va.predict("topp", q))["f1"]) for q in P_GRID), key=lambda v: v[1])[0]
        for tau in cfg["tau_grid"]:
            matcher = TemplateMatcher(known, tau=tau)
            cache: dict = {}

            def mapper_for(seq, comp, lvl):
                def f(i):
                    key = (int(seq[i]), int(comp[i]), int(lvl[i]))
                    if key not in cache:
                        cache[key] = matcher.match(ttext[key[0]], comps[key[1]], "error" if key[2] else "info")
                    return cache[key][0]
                return f

            for policy in (POLICIES if tau == cfg["tau_grid"][0] else ["P4"]):
                seqs = [apply_policy(ss.seqs[i], ss.levels[i], policy, V,
                                     mapper_for(ss.seqs[i], ss.components[i], ss.levels[i]))
                        for i in te]
                st = step_stats(model, seqs, cfg["h"])
                name = f"DeepLog+{policy}"
                tau_s = tau if policy == "P4" else "-"
                m = prf(ss.labels[te], st.predict("topg", g))
                rows.append(_row("bgl", "chrono", name, seed, m, f"src=bgl;policy={policy};tau={tau_s};rule=topg;g={g}"))
                m = prf(ss.labels[te], st.predict("topp", pp))
                rows.append(_row("bgl", "chrono", name, seed, m, f"src=bgl;policy={policy};tau={tau_s};rule=topp;p={pp}"))
            if tau == cfg["tau"]:
                for (eid, ci, lv), (mapped, score) in cache.items():
                    mapping_rows.append({"novel_event": eid, "novel_template": ttext[eid], "component": comps[ci],
                                         "level_class": "error" if lv else "info",
                                         "mapped_to": mapped, "mapped_template": ttext.get(mapped, "") if mapped else "",
                                         "similarity": round(score, 3), "correct (hand-check)": ""})
    novel_share = np.mean([np.any(np.asarray(ss.seqs[i]) >= NOVEL_BASE) for i in te])
    rows.append(_metric("bgl", "chrono", "-", 0, "test_windows_with_unseen_template", float(novel_share), "src=bgl"))
    write_results("E10", rows, tag="src=bgl")
    out = PROCESSED.parent.parent / "reports" / "bgl_matcher_mapping.csv"
    pd.DataFrame(mapping_rows).sort_values("similarity", ascending=False).to_csv(out, index=False)
    return rows
