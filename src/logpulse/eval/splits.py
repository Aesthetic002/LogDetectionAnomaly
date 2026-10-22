"""Chronological (default) and random (E3 only) splits — note 07 'Splitting rules'."""
from __future__ import annotations

import numpy as np


def chronological(time_key, train: float = 0.8, val_of_train: float = 0.1):
    """Sort by first timestamp; first 80% train, last 20% test; val = last 10% of train."""
    order = np.argsort(np.asarray(time_key), kind="stable")
    n_train = int(train * len(order))
    n_val = int(val_of_train * n_train)
    return order[: n_train - n_val], order[n_train - n_val: n_train], order[n_train:]


def random_split(n: int, seed: int = 0, train: float = 0.8, val_of_train: float = 0.1):
    order = np.random.default_rng(seed).permutation(n)
    n_train = int(train * n)
    n_val = int(val_of_train * n_train)
    return order[: n_train - n_val], order[n_train - n_val: n_train], order[n_train:]


def make_split(kind: str, time_key, seed: int = 0, **kw):
    return chronological(time_key, **kw) if kind == "chrono" else random_split(len(time_key), seed, **kw)
