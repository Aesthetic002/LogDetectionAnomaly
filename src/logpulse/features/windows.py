"""BGL windows: fixed-count (20 / 100 lines) and sliding time windows (1 h, 30 min step)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from logpulse.features.sessionize import SessionSet
from logpulse.parsing.drain_parser import LEVEL_CODE, level_class
from logpulse.paths import PROCESSED


def load_bgl_lines() -> pd.DataFrame:
    return pd.read_parquet(PROCESSED / "bgl" / "lines.parquet")


def fixed_windows(lines: pd.DataFrame, size: int = 20, mode: str = "honest") -> SessionSet:
    """Non-overlapping windows of ``size`` consecutive lines (log order = time order).

    A window is anomalous if any of its lines carries a non-'-' label.
    """
    n = (len(lines) // size) * size
    eids = lines[f"eid_{mode}"].to_numpy()[:n].reshape(-1, size)
    lab = lines["is_anom"].to_numpy()[:n].reshape(-1, size).max(axis=1).astype(np.int8)
    ts = lines["ts"].to_numpy()[:n].reshape(-1, size)[:, 0]
    comp = lines["component"].cat.codes.to_numpy()[:n].reshape(-1, size)
    codes = {lv: LEVEL_CODE[level_class(lv)] for lv in lines["level"].cat.categories}
    lvl = lines["level"].map(codes).astype(np.int8).to_numpy()[:n].reshape(-1, size)  # 0 info, 1 warn, 2 error
    return SessionSet(
        seqs=list(eids), labels=lab, time_key=np.arange(len(lab)),  # line order is the clock
        components=list(comp), levels=list(lvl.astype(np.int8)),
        meta={"dataset": "bgl", "mode": mode, "window": f"fixed{size}",
              "component_names": list(lines["component"].cat.categories), "first_ts": ts},
    )


def time_windows(lines: pd.DataFrame, window_s: int = 3600, step_s: int = 1800, mode: str = "honest") -> SessionSet:
    """Sliding time windows. Lines are stably sorted by timestamp first."""
    order = np.argsort(lines["ts"].to_numpy(), kind="stable")
    ts = lines["ts"].to_numpy()[order]
    eids = lines[f"eid_{mode}"].to_numpy()[order]
    anom = lines["is_anom"].to_numpy()[order]
    starts = np.arange(ts[0], ts[-1] - window_s + step_s, step_s)
    lo = np.searchsorted(ts, starts, side="left")
    hi = np.searchsorted(ts, starts + window_s, side="left")
    keep = hi > lo
    seqs = [eids[a:b] for a, b, k in zip(lo, hi, keep) if k]
    labels = np.array([anom[a:b].max() for a, b, k in zip(lo, hi, keep) if k], dtype=np.int8)
    return SessionSet(seqs=seqs, labels=labels, time_key=starts[keep],
                      meta={"dataset": "bgl", "mode": mode, "window": f"time{window_s}s/{step_s}s"})
