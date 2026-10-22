"""Improvement 1 — semantic template matcher for unstable logs (note 15).

A template never seen in training is mapped to the most similar *known* template of the
same service (component) and the same severity class, if the TF-IDF cosine similarity
reaches tau. Unmatched ERROR/WARN templates stay anomalous; unmatched INFO templates are
neutral (skipped in scoring and queued for review).
"""
from __future__ import annotations

import re

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def clean(t: str) -> str:
    """Drop wildcards and masks, lowercase."""
    return re.sub(r"<[^>]*>", " ", t).lower()


class TemplateMatcher:
    def __init__(self, known: list[tuple[int, str, str, str]], tau: float = 0.6):
        """known: list of (event_id, template, service, level_class); an event may appear
        under several (service, level) pairs."""
        self.known = known
        self.tau = tau
        self.vec = TfidfVectorizer(token_pattern=r"[a-z]{2,}")
        self.K = self.vec.fit_transform([clean(k[1]) for k in known])
        self.svc = np.array([k[2] for k in known], dtype=object)
        self.lvl = np.array([k[3] for k in known], dtype=object)
        self.eids = np.array([k[0] for k in known])

    def similarities(self, template: str) -> np.ndarray:
        return cosine_similarity(self.vec.transform([clean(template)]), self.K)[0]

    def match(self, template: str, service: str, level_class: str):
        """Return (event_id or None, best_similarity)."""
        sims = self.similarities(template)
        ok = (self.svc == service) & (self.lvl == level_class)
        if not ok.any():
            return None, 0.0
        sims = np.where(ok, sims, -1.0)
        i = int(np.argmax(sims))
        best = float(sims[i])
        return (int(self.eids[i]), best) if best >= self.tau else (None, best)


# ---------------------------------------------------------------- unseen-template policies

POLICIES = ["P1", "P2", "P3", "P4"]
POLICY_NAMES = {"P1": "vanilla (unseen = anomaly)", "P2": "ignore unseen",
                "P3": "severity only", "P4": "semantic matcher (ours)"}


def apply_policy(seq, is_error, policy: str, vocab_size: int, mapping: dict | None = None):
    """Transform one event sequence according to an unseen-template policy.

    seq       event ids; ids >= vocab_size are unseen (novel) templates
    is_error  per-event severity (nonzero = WARN/ERROR class)
    mapping   for P4: {(novel_id, is_error_flag, *ctx) -> known id or None} via a callable
    Returns the new sequence; UNSEEN (1) marks an anomalous unseen step, dropped events
    are neutral.
    """
    from logpulse.paths import UNSEEN

    seq = np.asarray(seq)
    novel = seq >= vocab_size
    if not novel.any():
        return seq
    if policy == "P1":
        return np.where(novel, UNSEEN, seq)
    if policy == "P2":
        return seq[~novel]
    err = np.asarray(is_error).astype(bool)
    if policy == "P3":
        out = np.where(novel & err, UNSEEN, seq)
        return out[~(novel & ~err)]
    if policy == "P4":
        out = seq.copy()
        keep = np.ones(len(seq), dtype=bool)
        for i in np.flatnonzero(novel):
            mapped = mapping(i) if callable(mapping) else None
            if mapped is not None:
                out[i] = mapped
            elif err[i]:
                out[i] = UNSEEN
            else:
                keep[i] = False
        return out[keep]
    raise ValueError(policy)
