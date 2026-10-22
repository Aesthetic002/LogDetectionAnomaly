"""DeepLog-style LSTM next-event model (Du et al., CCS 2017) + our decision rules.

Training uses only normal sequences. For every position the model sees the previous h
event ids (PAD-padded) and predicts the next one.

Scoring is done once per step and stored as three statistics, so every decision rule is
evaluated from the *same* forward pass (clean comparison for E11):

    rank         1-based rank of the actual event in the predicted distribution
    mass_before  total probability of events ranked above the actual event
    logp         log-probability of the actual event

    top-g     : anomalous step  <=>  rank > g                     (vanilla DeepLog)
    top-p     : anomalous step  <=>  mass_before >= p               (ours, improvement 2)
    surprise  : anomalous step  <=>  -logp > theta                  (variant)

The actual event being UNSEEN (id 1) is always an anomalous step. A sequence is anomalous
if any step is.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
import torch
import torch.nn as nn

from logpulse.paths import PAD, UNSEEN


class DeepLog(nn.Module):
    def __init__(self, n_events: int, emb: int = 32, hidden: int = 64, layers: int = 2):
        super().__init__()
        self.n_events = n_events
        self.cfg = {"n_events": n_events, "emb": emb, "hidden": hidden, "layers": layers}
        self.emb = nn.Embedding(n_events, emb, padding_idx=PAD)
        self.lstm = nn.LSTM(emb, hidden, layers, batch_first=True)
        self.fc = nn.Linear(hidden, n_events)

    def forward(self, x):
        out, _ = self.lstm(self.emb(x))
        return self.fc(out[:, -1, :])

    def save(self, path, extra: dict | None = None):
        torch.save({"cfg": self.cfg, "state": self.state_dict(), **(extra or {})}, path)

    @classmethod
    def load(cls, path):
        ck = torch.load(path, map_location="cpu", weights_only=False)
        m = cls(**ck["cfg"])
        m.load_state_dict(ck["state"])
        m.eval()
        return m, ck


# ---------------------------------------------------------------- windows

def windows(seqs, h: int):
    """All (window, target) pairs. Returns X [N,h] int32, y [N] int32, owner [N] (seq index)."""
    lens = np.fromiter((len(s) for s in seqs), dtype=np.int64, count=len(seqs))
    total = int(lens.sum())
    X = np.empty((total, h), dtype=np.int32)
    y = np.empty(total, dtype=np.int32)
    owner = np.repeat(np.arange(len(seqs)), lens)
    pos = 0
    for s in seqs:
        n = len(s)
        if n == 0:
            continue
        padded = np.concatenate([np.full(h, PAD, dtype=np.int32), np.asarray(s, dtype=np.int32)])
        X[pos:pos + n] = np.lib.stride_tricks.sliding_window_view(padded, h)[:n]
        y[pos:pos + n] = padded[h:]
        pos += n
    return X, y, owner


def dedupe(X, y, weights=None):
    """Unique (window, target) rows with occurrence counts — the training set shrinks
    from millions of rows to thousands while the weighted loss stays identical."""
    rows = np.ascontiguousarray(np.column_stack([X, y]).astype(np.int32))
    view = rows.view(np.dtype((np.void, rows.dtype.itemsize * rows.shape[1]))).ravel()
    _, idx, inv = np.unique(view, return_index=True, return_inverse=True)
    w = np.bincount(inv, weights=weights, minlength=len(idx)).astype(np.float32)
    return rows[idx, :-1], rows[idx, -1], w, inv


# ---------------------------------------------------------------- training

@dataclass
class TrainLog:
    epochs: int
    train_loss: list
    val_loss: list
    seconds: float


def _weighted_loss(model, X, y, w, bs, device):
    model.eval()
    tot, wsum = 0.0, 0.0
    ce = nn.CrossEntropyLoss(reduction="none")
    with torch.no_grad():
        for a in range(0, len(y), bs):
            xb = torch.as_tensor(X[a:a + bs], dtype=torch.long, device=device)
            yb = torch.as_tensor(y[a:a + bs], dtype=torch.long, device=device)
            wb = torch.as_tensor(w[a:a + bs], device=device)
            tot += float((ce(model(xb), yb) * wb).sum())
            wsum += float(wb.sum())
    return tot / max(wsum, 1e-9)


def train(model: DeepLog, seqs, h=10, epochs=30, lr=1e-3, bs=256, val_seqs=None, patience=3,
          seed=0, device="cpu", verbose=True, max_steps=1000) -> TrainLog:
    """Minibatches are drawn from the unique pairs with probability proportional to their
    count — the same expected gradient as iterating over every window, at a fraction of
    the cost. One epoch = sum(counts)/bs steps (capped at max_steps)."""
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    X, y, _ = windows(seqs, h)
    X, y, w, _ = dedupe(X, y)
    prob = w / w.sum()
    steps = int(min(max(np.ceil(w.sum() / bs), 50), max_steps))
    if val_seqs is not None and len(val_seqs):
        Xv, yv, _ = windows(val_seqs, h)
        Xv, yv, wv, _ = dedupe(Xv, yv)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    ce = nn.CrossEntropyLoss()
    model.to(device)
    t0 = time.time()
    tl, vl = [], []
    best, best_state, bad = float("inf"), None, 0
    for ep in range(epochs):
        model.train()
        idx = rng.choice(len(y), size=steps * bs, p=prob)
        tot = 0.0
        for a in range(0, len(idx), bs):
            b = idx[a:a + bs]
            xb = torch.as_tensor(X[b], dtype=torch.long, device=device)
            yb = torch.as_tensor(y[b], dtype=torch.long, device=device)
            opt.zero_grad()
            loss = ce(model(xb), yb)
            loss.backward()
            opt.step()
            tot += loss.item()
        tl.append(tot / steps)
        if val_seqs is not None and len(val_seqs):
            vl.append(_weighted_loss(model, Xv, yv, wv, 8192, device))
            if verbose:
                print(f"    epoch {ep}: train {tl[-1]:.4f}  val {vl[-1]:.4f}  ({len(y):,} unique pairs)", flush=True)
            if vl[-1] < best - 1e-4:
                best, bad = vl[-1], 0
                best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
            else:
                bad += 1
                if bad >= patience:
                    break
        elif verbose:
            print(f"    epoch {ep}: train {tl[-1]:.4f}", flush=True)
    if best_state is not None:
        model.load_state_dict(best_state)
    model.eval()
    return TrainLog(len(tl), tl, vl, time.time() - t0)


# ---------------------------------------------------------------- scoring

@dataclass
class StepStats:
    """Per-step statistics for a list of sequences (flattened, with offsets)."""
    actual: np.ndarray
    rank: np.ndarray
    mass_before: np.ndarray
    logp: np.ndarray
    offsets: np.ndarray  # len = n_seqs + 1

    def per_seq_any(self, step_flags: np.ndarray) -> np.ndarray:
        n = len(self.offsets) - 1
        out = np.zeros(n, dtype=bool)
        lens = np.diff(self.offsets)
        nz = lens > 0
        if step_flags.size:
            red = np.maximum.reduceat(step_flags.astype(np.int8), self.offsets[:-1][nz])
            out[nz] = red.astype(bool)
        return out

    def first_bad(self, step_flags: np.ndarray) -> np.ndarray:
        """Index of the first anomalous step per sequence (-1 if none)."""
        out = np.full(len(self.offsets) - 1, -1)
        bad = np.flatnonzero(step_flags)
        if bad.size:
            owner = np.searchsorted(self.offsets, bad, side="right") - 1
            first = np.unique(owner, return_index=True)
            out[first[0]] = bad[first[1]] - self.offsets[first[0]]
        return out

    # decision rules ------------------------------------------------
    def steps_topg(self, g: int):
        return (self.actual == UNSEEN) | (self.rank > g)

    def steps_topp(self, p: float):
        return (self.actual == UNSEEN) | (self.mass_before >= p)

    def steps_surprise(self, theta: float):
        return (self.actual == UNSEEN) | (-self.logp > theta)

    def steps(self, rule: str, param: float):
        return {"topg": self.steps_topg, "topp": self.steps_topp, "surprise": self.steps_surprise}[rule](param)

    def predict(self, rule: str, param: float) -> np.ndarray:
        return self.per_seq_any(self.steps(rule, param))

    def seq_score(self) -> np.ndarray:
        """Threshold-free score for PR-AUC: max per-step surprise (UNSEEN = +inf)."""
        s = np.where(self.actual == UNSEEN, 50.0, -self.logp)
        out = np.zeros(len(self.offsets) - 1)
        lens = np.diff(self.offsets)
        nz = lens > 0
        if s.size:
            out[nz] = np.maximum.reduceat(s, self.offsets[:-1][nz])
        return out


@torch.no_grad()
def step_stats(model: DeepLog, seqs, h: int, bs: int = 4096, device="cpu") -> StepStats:
    """Score every step of every sequence; each distinct window is run through the LSTM once."""
    model.eval().to(device)
    V = model.n_events
    seqs = [np.where(np.asarray(s) >= V, UNSEEN, np.asarray(s)) for s in seqs]
    X, y, _ = windows(seqs, h)
    offsets = np.concatenate([[0], np.cumsum([len(s) for s in seqs])]).astype(np.int64)
    if len(y) == 0:
        z = np.zeros(0)
        return StepStats(y, z, z, z, offsets)
    Xu, yu, _, inv = dedupe(X, y)
    rank = np.empty(len(yu))
    mass = np.empty(len(yu))
    logp = np.empty(len(yu))
    for a in range(0, len(yu), bs):
        xb = torch.as_tensor(Xu[a:a + bs], dtype=torch.long, device=device)
        yb = torch.as_tensor(yu[a:a + bs], dtype=torch.long, device=device)
        probs = torch.softmax(model(xb), dim=-1)
        pa = probs.gather(1, yb[:, None])
        greater = probs > pa
        rank[a:a + bs] = (greater.sum(1) + 1).cpu().numpy()
        mass[a:a + bs] = (probs * greater).sum(1).cpu().numpy()
        logp[a:a + bs] = torch.log(pa.squeeze(1).clamp_min(1e-12)).cpu().numpy()
    return StepStats(y, rank[inv], mass[inv], logp[inv], offsets)


@torch.no_grad()
def predict_next(model: DeepLog, history, h: int, top: int = 5):
    """Distribution for the next event given the last h events (online, step-wise scoring)."""
    hist = [PAD] * h + [e if e < model.n_events else UNSEEN for e in history]
    x = torch.as_tensor([hist[-h:]], dtype=torch.long)
    return torch.softmax(model(x), dim=-1)[0]


def allowed_set(probs: torch.Tensor, rule: str, param: float) -> list[int]:
    sorted_p, order = probs.sort(descending=True)
    if rule == "topg":
        k = int(param)
    elif rule == "topp":
        k = int((sorted_p.cumsum(0) < param).sum()) + 1
    else:  # surprise: every event with -log p <= theta
        k = int((-torch.log(sorted_p.clamp_min(1e-12)) <= param).sum())
    return order[:k].tolist()
