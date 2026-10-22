"""Count matrices for the classical models (note 05) and their variants (E7)."""
from __future__ import annotations

import numpy as np
from scipy.sparse import csr_matrix, hstack
from sklearn.feature_extraction.text import TfidfTransformer

from logpulse.paths import NOVEL_BASE, UNSEEN


def to_known(seq: np.ndarray, vocab_size: int) -> np.ndarray:
    """Map novel / out-of-vocabulary ids to UNSEEN so they share one column."""
    seq = np.asarray(seq)
    return np.where((seq >= vocab_size) | (seq >= NOVEL_BASE), UNSEEN, seq)


def count_matrix(seqs, n_events: int) -> csr_matrix:
    lens = np.fromiter((len(s) for s in seqs), dtype=np.int64, count=len(seqs))
    if lens.sum() == 0:
        return csr_matrix((len(seqs), n_events))
    rows = np.repeat(np.arange(len(seqs)), lens)
    cols = np.concatenate([to_known(s, n_events) for s in seqs if len(s)])
    m = csr_matrix((np.ones_like(cols, dtype=np.float32), (rows, cols)), shape=(len(seqs), n_events))
    m.sum_duplicates()
    return m


class Featurizer:
    """kind: count | tfidf | binary | count+len. Fit on train only."""

    def __init__(self, kind: str = "count"):
        self.kind = kind
        self.tfidf = TfidfTransformer() if kind == "tfidf" else None

    def fit(self, X: csr_matrix):
        if self.tfidf is not None:
            self.tfidf.fit(X)
        return self

    def transform(self, X: csr_matrix) -> csr_matrix:
        if self.kind == "tfidf":
            return self.tfidf.transform(X).astype(np.float32)
        if self.kind == "binary":
            B = X.copy()
            B.data[:] = 1.0
            return B
        if self.kind == "count+len":
            return hstack([X, csr_matrix(np.asarray(X.sum(axis=1)))]).tocsr()
        return X
