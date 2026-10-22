"""Metrics + the single results file every reported number traces back to (note 07)."""
from __future__ import annotations

import os
import time
from contextlib import contextmanager

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, precision_recall_fscore_support

from logpulse.paths import RESULTS_CSV

COLUMNS = ["exp_id", "dataset", "split", "model", "seed", "precision", "recall", "f1",
           "pr_auc", "train_time_s", "metric", "value", "notes"]


def prf(y_true, y_pred) -> dict:
    p, r, f1, _ = precision_recall_fscore_support(y_true, y_pred, average="binary", zero_division=0)
    return {"precision": float(p), "recall": float(r), "f1": float(f1)}


def pr_auc(y_true, score) -> float:
    if score is None or len(np.unique(y_true)) < 2:
        return float("nan")
    return float(average_precision_score(y_true, score))


def best_threshold(y_true, score) -> tuple[float, float]:
    """Threshold on a validation score that maximises F1 (score >= thr -> anomaly)."""
    score = np.asarray(score, dtype=float)
    cands = np.unique(np.quantile(score, np.linspace(0.5, 1.0, 201)))
    best = (float(cands[-1]), -1.0)
    for thr in cands:
        f = prf(y_true, score >= thr)["f1"]
        if f > best[1]:
            best = (float(thr), f)
    return best


@contextmanager
def _locked(path, timeout=120):
    """Cross-process lock (several scripts append to results.csv concurrently)."""
    lock = str(path) + ".lock"
    t0 = time.time()
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            if time.time() - t0 > timeout:
                os.remove(lock)  # stale lock from a crashed writer
            time.sleep(0.2)
    try:
        yield
    finally:
        os.close(fd)
        os.remove(lock)


def write_results(exp_id: str, rows: list[dict], tag: str | None = None) -> pd.DataFrame:
    """Replace this experiment's rows (optionally only those with notes containing tag)."""
    RESULTS_CSV.parent.mkdir(parents=True, exist_ok=True)
    with _locked(RESULTS_CSV):
        return _write_results(exp_id, rows, tag)


def _write_results(exp_id, rows, tag):
    old = pd.read_csv(RESULTS_CSV) if RESULTS_CSV.exists() else pd.DataFrame(columns=COLUMNS)
    drop = old["exp_id"] == exp_id
    if tag is not None:
        drop &= old["notes"].fillna("").str.contains(tag, regex=False)
    new = pd.DataFrame([{**{c: None for c in COLUMNS}, "exp_id": exp_id, **r} for r in rows], columns=COLUMNS)
    out = pd.concat([old[~drop], new], ignore_index=True) if len(old[~drop]) else new
    out.to_csv(RESULTS_CSV, index=False)
    return out
