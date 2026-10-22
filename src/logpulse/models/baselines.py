"""Classical baselines on event-count matrices (note 05).

Supervised: LR, DT, NB, RF (class_weight='balanced' where available).
Unsupervised: PCA (SPE, Xu et al. SOSP'09) and Isolation Forest; their score thresholds
are chosen on the validation slice, never on test.
"""
from __future__ import annotations

import numpy as np
from scipy.sparse import csr_matrix, issparse
from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.naive_bayes import MultinomialNB
from sklearn.tree import DecisionTreeClassifier

SUPERVISED = ["LR", "DT", "NB", "RF"]
UNSUPERVISED = ["PCA", "IsoForest"]


def make_supervised(name: str, seed: int = 0, max_depth: int | None = 10):
    if name == "LR":
        return LogisticRegression(max_iter=2000, class_weight="balanced", random_state=seed)
    if name == "DT":
        return DecisionTreeClassifier(max_depth=max_depth, class_weight="balanced", random_state=seed)
    if name == "NB":
        return MultinomialNB()
    if name == "RF":
        return RandomForestClassifier(n_estimators=300, class_weight="balanced", n_jobs=-1, random_state=seed)
    raise ValueError(name)


class PCADetector:
    """Normal subspace from the top principal components explaining ``var`` of the variance;
    anomaly score = squared prediction error (SPE) of the residual. Works on sparse input by
    forming the (small) covariance matrix directly and scoring in dense chunks."""

    def __init__(self, var: float = 0.95):
        self.var = var

    def fit(self, X):
        X = csr_matrix(X, dtype=np.float64)
        n = X.shape[0]
        self.mu = np.asarray(X.mean(axis=0)).ravel()
        cov = (X.T @ X).toarray() / n - np.outer(self.mu, self.mu)
        vals, vecs = np.linalg.eigh(cov)
        order = np.argsort(vals)[::-1]
        vals, vecs = np.clip(vals[order], 0, None), vecs[:, order]
        frac = np.cumsum(vals) / max(vals.sum(), 1e-12)
        k = int(np.searchsorted(frac, self.var) + 1)
        self.P = vecs[:, :k]
        self.k = k
        return self

    def score(self, X, chunk: int = 20000) -> np.ndarray:
        out = np.empty(X.shape[0])
        for a in range(0, X.shape[0], chunk):
            D = X[a:a + chunk]
            D = (D.toarray() if issparse(D) else np.asarray(D)) - self.mu
            R = D - (D @ self.P) @ self.P.T
            out[a:a + chunk] = (R ** 2).sum(axis=1)
        return out


class IsoForestDetector:
    def __init__(self, seed: int = 0):
        self.m = IsolationForest(n_estimators=300, contamination="auto", random_state=seed, n_jobs=-1)

    def fit(self, X):
        self.m.fit(X)
        return self

    def score(self, X) -> np.ndarray:
        return -self.m.score_samples(X)  # higher = more anomalous
