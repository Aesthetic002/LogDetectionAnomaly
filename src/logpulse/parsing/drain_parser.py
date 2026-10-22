"""Drain3 parsing for HDFS, BGL and the demo app (note 04).

Two parse modes are produced for the benchmarks:

* ``full``   — Drain learns from every line (the common, leaky practice; used for E3).
* ``honest`` — Drain learns only from the training period; test-period lines are
  ``match()``-ed against the frozen tree. Lines that match nothing are mined by a
  separate "novel" miner so they still get a template (ids >= NOVEL_BASE) — the
  unseen-template policies (E6/E10) decide what the model sees for them.

Speed trick: Drain's output for a line depends only on its *masked* content, so each
distinct masked string is sent through the tree once, in order of first occurrence.
That is exactly what streaming every line would produce, at a fraction of the cost.
"""
from __future__ import annotations

import argparse
import calendar
import json
import re
import time
from array import array
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from drain3 import TemplateMiner
from drain3.file_persistence import FilePersistence
from drain3.template_miner_config import TemplateMinerConfig

from logpulse.paths import DRAIN_INI, NOVEL_BASE, PROCESSED, RAW

HDFS_RE = re.compile(r"^(\d{6}) (\d{6}) (\d+) (\w+) ([\w.$]+): (.*)$")
BLK_RE = re.compile(r"blk_-?\d+")
ERRORISH = {"WARN", "WARNING", "ERROR", "FATAL", "SEVERE", "FAILURE", "CRITICAL"}


def level_class(level: str) -> str:
    """Two severity classes used by the template matcher and the severity policy."""
    return "error" if str(level).upper() in ERRORISH else "info"


def make_miner(cfg_path=DRAIN_INI, sim_th=None, depth=None, masking=True, state_path=None):
    cfg = TemplateMinerConfig()
    cfg.load(str(cfg_path))
    if sim_th is not None:
        cfg.drain_sim_th = sim_th
    if depth is not None:
        cfg.drain_depth = depth
    if not masking:
        cfg.masking_instructions = []
    persistence = FilePersistence(str(state_path)) if state_path else None
    return TemplateMiner(persistence, cfg)


class CachedMiner:
    """TemplateMiner + a masked-content -> cluster_id cache (see module docstring)."""

    def __init__(self, miner: TemplateMiner):
        self.miner = miner
        self._learned: dict[str, int] = {}
        self._matched: dict[str, int | None] = {}

    def mask(self, content: str) -> str:
        return self.miner.masker.mask(content.strip())

    def learn_masked(self, masked: str) -> int:
        cid = self._learned.get(masked)
        if cid is None:
            cluster, _ = self.miner.drain.add_log_message(masked)
            cid = cluster.cluster_id
            self._learned[masked] = cid
            self._matched.clear()  # tree changed; cached misses may now match
        return cid

    def match_masked(self, masked: str) -> int | None:
        if masked in self._learned:
            return self._learned[masked]
        if masked not in self._matched:
            c = self.miner.drain.match(masked)
            self._matched[masked] = c.cluster_id if c else None
        return self._matched[masked]

    def templates(self) -> dict[int, str]:
        return {c.cluster_id: c.get_template() for c in self.miner.drain.clusters}


# ---------------------------------------------------------------- parsing accuracy (E1)

def grouping_accuracy(true_ids, pred_ids) -> float:
    """Loghub GA: a line is correct iff its predicted group equals its true group exactly."""
    df = pd.DataFrame({"t": list(true_ids), "p": list(pred_ids)})
    true_sizes = df["t"].value_counts()
    correct = 0
    for _, grp in df.groupby("p"):
        t_vals = grp["t"].unique()
        if len(t_vals) == 1 and true_sizes[t_vals[0]] == len(grp):
            correct += len(grp)
    return correct / len(df)


def parse_2k(dataset: str, sim_th=0.5, masking=True, depth=None) -> dict:
    """Parse a Loghub-2k sample line by line (plain Drain3, no cache) and score it."""
    df = pd.read_csv(RAW / "loghub-2k" / f"{dataset}_2k.log_structured.csv")
    miner = make_miner(sim_th=sim_th, masking=masking, depth=depth)
    t0 = time.perf_counter()
    pred = [miner.add_log_message(str(c))["cluster_id"] for c in df["Content"]]
    elapsed = time.perf_counter() - t0
    return {
        "dataset": f"{dataset}-2k", "sim_th": sim_th, "masking": masking,
        "ga": grouping_accuracy(df["EventId"], pred),
        "templates_found": len(set(pred)), "true_templates": df["EventId"].nunique(),
        "lines_per_sec": len(df) / elapsed,
    }


# ---------------------------------------------------------------- shared two-mode parse

def _two_mode_ids(uniq: list[str], first_pos: np.ndarray, boundary, sim_th, depth=None):
    """Return (eid_full, eid_honest, templates_full, templates_honest) per unique masked string.

    ``first_pos`` is each string's first-occurrence position (time or line index);
    strings first seen before ``boundary`` are training-period strings.
    """
    full = CachedMiner(make_miner(sim_th=sim_th, depth=depth))
    eid_full = np.array([full.learn_masked(s) + 1 for s in uniq], dtype=np.int64)

    honest = CachedMiner(make_miner(sim_th=sim_th, depth=depth))
    novel = CachedMiner(make_miner(sim_th=sim_th, depth=depth))
    train_mask = first_pos < boundary
    eid_honest = np.zeros(len(uniq), dtype=np.int64)
    for i in np.flatnonzero(train_mask):
        eid_honest[i] = honest.learn_masked(uniq[i]) + 1
    for i in np.flatnonzero(~train_mask):
        cid = honest.match_masked(uniq[i])
        eid_honest[i] = cid + 1 if cid is not None else NOVEL_BASE + novel.learn_masked(uniq[i])

    t_full = {cid + 1: t for cid, t in full.templates().items()}
    t_honest = {cid + 1: t for cid, t in honest.templates().items()}
    t_honest.update({NOVEL_BASE + cid: t for cid, t in novel.templates().items()})
    return eid_full, eid_honest, t_full, t_honest


def _save_templates(path: Path, templates: dict, line_eids: np.ndarray):
    ids, counts = np.unique(line_eids, return_counts=True)
    occ = dict(zip(ids.tolist(), counts.tolist()))
    rows = [(e, t, occ.get(e, 0), e >= NOVEL_BASE) for e, t in sorted(templates.items())]
    pd.DataFrame(rows, columns=["EventId", "EventTemplate", "Occurrences", "Novel"]).to_csv(path, index=False)


# ---------------------------------------------------------------- HDFS

def _hdfs_epoch(date: str, tm: str, cache: dict) -> int:
    base = cache.get(date)
    if base is None:
        base = calendar.timegm((2000 + int(date[:2]), int(date[2:4]), int(date[4:6]), 0, 0, 0))
        cache[date] = base
    return base + int(tm[:2]) * 3600 + int(tm[2:4]) * 60 + int(tm[4:6])


def parse_hdfs(log_path=None, label_path=None, out_dir=None, sim_th=0.5, train_frac=0.8, limit=None):
    log_path = Path(log_path or RAW / "HDFS_v1" / "HDFS.log")
    label_path = Path(label_path or RAW / "HDFS_v1" / "preprocessed" / "anomaly_label.csv")
    out_dir = Path(out_dir or PROCESSED / "hdfs")
    out_dir.mkdir(parents=True, exist_ok=True)

    masker = make_miner(sim_th=sim_th).masker
    uniq_idx: dict[str, int] = {}
    uniq: list[str] = []
    first_ts: list[int] = []
    line_masked = array("I")
    line_ts = array("I")
    pair_blk = array("i")
    pair_line = array("I")
    blk_index: dict[str, int] = {}
    date_cache: dict = {}

    t0 = time.perf_counter()
    n = 0
    with open(log_path, errors="ignore") as f:
        for line in f:
            m = HDFS_RE.match(line.rstrip("\n"))
            if not m:
                continue
            date, tm, _pid, _level, _component, content = m.groups()
            ts = _hdfs_epoch(date, tm, date_cache)
            masked = masker.mask(content.strip())
            i = uniq_idx.get(masked)
            if i is None:
                i = uniq_idx[masked] = len(uniq)
                uniq.append(masked)
                first_ts.append(ts)
            line_masked.append(i)
            line_ts.append(ts)
            for b in set(BLK_RE.findall(content)):
                bi = blk_index.get(b)
                if bi is None:
                    bi = blk_index[b] = len(blk_index)
                pair_blk.append(bi)
                pair_line.append(n)
            n += 1
            if n % 1_000_000 == 0:
                print(f"  hdfs {n:,} lines, {len(uniq):,} masked strings, {time.perf_counter() - t0:.0f}s", flush=True)
            if limit and n >= limit:
                break
    read_s = time.perf_counter() - t0

    line_masked = np.frombuffer(line_masked, dtype=np.uint32)
    line_ts = np.frombuffer(line_ts, dtype=np.uint32).astype(np.int64)
    pair_blk = np.frombuffer(pair_blk, dtype=np.int32)
    pair_line = np.frombuffer(pair_line, dtype=np.uint32)

    # sessions: lines grouped by block, kept in log order
    order = np.argsort(pair_blk, kind="stable")
    sess_lines = pair_line[order]
    counts = np.bincount(pair_blk, minlength=len(blk_index))
    offsets = np.concatenate([[0], np.cumsum(counts)]).astype(np.int64)
    sess_first_ts = line_ts[sess_lines[offsets[:-1]]]

    # chronological boundary: first timestamp of the session at the train_frac quantile
    sorted_first = np.sort(sess_first_ts)
    boundary = int(sorted_first[int(train_frac * len(sorted_first))])

    t1 = time.perf_counter()
    eid_full, eid_honest, t_full, t_honest = _two_mode_ids(uniq, np.array(first_ts), boundary, sim_th)
    drain_s = time.perf_counter() - t1

    line_full = eid_full[line_masked]
    line_honest = eid_honest[line_masked]

    labels = pd.read_csv(label_path)
    lab = dict(zip(labels["BlockId"], (labels["Label"] == "Anomaly").astype(np.int8)))
    blk_names = np.empty(len(blk_index), dtype=object)
    for b, bi in blk_index.items():
        blk_names[bi] = b
    y = np.array([lab.get(b, 0) for b in blk_names], dtype=np.int8)

    off = pa.array(offsets.astype(np.int32))
    table = pa.table({
        "BlockId": pa.array(blk_names.tolist()),
        "first_ts": pa.array(sess_first_ts),
        "label": pa.array(y),
        "n": pa.array(counts.astype(np.int32)),
        "seq_full": pa.ListArray.from_arrays(off, pa.array(line_full[sess_lines].astype(np.int32))),
        "seq_honest": pa.ListArray.from_arrays(off, pa.array(line_honest[sess_lines].astype(np.int32))),
    })
    pq.write_table(table, out_dir / "sessions.parquet")
    _save_templates(out_dir / "templates_full.csv", t_full, line_full)
    _save_templates(out_dir / "templates_honest.csv", t_honest, line_honest)
    meta = {
        "dataset": "hdfs", "lines": int(n), "sessions": int(len(blk_index)),
        "anomalous_sessions": int(y.sum()), "masked_strings": len(uniq),
        "templates_full": len(t_full), "templates_honest_train": sum(e < NOVEL_BASE for e in t_honest),
        "templates_novel_test": sum(e >= NOVEL_BASE for e in t_honest),
        "boundary_ts": boundary, "train_frac": train_frac, "sim_th": sim_th,
        "read_mask_seconds": round(read_s, 1), "drain_seconds": round(drain_s, 2),
        "lines_per_sec_end_to_end": round(n / (read_s + drain_s)),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta, indent=2))
    return meta


# ---------------------------------------------------------------- BGL

def parse_bgl(log_path=None, out_dir=None, sim_th=0.5, train_frac=0.8, limit=None):
    log_path = Path(log_path or RAW / "BGL" / "BGL.log")
    out_dir = Path(out_dir or PROCESSED / "bgl")
    out_dir.mkdir(parents=True, exist_ok=True)

    masker = make_miner(sim_th=sim_th).masker
    uniq_idx: dict[str, int] = {}
    uniq: list[str] = []
    first_line: list[int] = []
    line_masked = array("I")
    line_ts = array("q")
    label_codes: dict[str, int] = {"-": 0}
    line_label = array("H")
    level_codes: dict[str, int] = {}
    line_level = array("B")
    comp_codes: dict[str, int] = {}
    line_comp = array("H")

    t0 = time.perf_counter()
    n = 0
    with open(log_path, errors="ignore") as f:
        for line in f:
            parts = line.rstrip("\n").split(" ", 9)
            if len(parts) < 9:
                continue
            label, ts = parts[0], parts[1]
            component, level = parts[7], parts[8]
            content = parts[9] if len(parts) > 9 else ""
            masked = masker.mask(content.strip())
            i = uniq_idx.get(masked)
            if i is None:
                i = uniq_idx[masked] = len(uniq)
                uniq.append(masked)
                first_line.append(n)
            line_masked.append(i)
            line_ts.append(int(ts) if ts.isdigit() else (line_ts[-1] if line_ts else 0))
            line_label.append(label_codes.setdefault(label, len(label_codes)))
            line_level.append(level_codes.setdefault(level, len(level_codes)))
            line_comp.append(comp_codes.setdefault(component, len(comp_codes)))
            n += 1
            if n % 1_000_000 == 0:
                print(f"  bgl {n:,} lines, {len(uniq):,} masked strings, {time.perf_counter() - t0:.0f}s", flush=True)
            if limit and n >= limit:
                break
    read_s = time.perf_counter() - t0

    boundary = int(train_frac * n)
    t1 = time.perf_counter()
    eid_full, eid_honest, t_full, t_honest = _two_mode_ids(uniq, np.array(first_line), boundary, sim_th)
    drain_s = time.perf_counter() - t1

    masked_arr = np.frombuffer(line_masked, dtype=np.uint32)
    line_full = eid_full[masked_arr]
    line_honest = eid_honest[masked_arr]
    inv = lambda d: {v: k for k, v in d.items()}  # noqa: E731
    lab_inv, lvl_inv, comp_inv = inv(label_codes), inv(level_codes), inv(comp_codes)
    lab_arr = np.frombuffer(line_label, dtype=np.uint16)
    df = pd.DataFrame({
        "ts": np.frombuffer(line_ts, dtype=np.int64),
        "is_anom": (lab_arr != 0).astype(np.int8),
        "label": pd.Categorical.from_codes(lab_arr, [lab_inv[i] for i in range(len(lab_inv))]),
        "level": pd.Categorical.from_codes(np.frombuffer(line_level, dtype=np.uint8), [lvl_inv[i] for i in range(len(lvl_inv))]),
        "component": pd.Categorical.from_codes(np.frombuffer(line_comp, dtype=np.uint16), [comp_inv[i] for i in range(len(comp_inv))]),
        "eid_full": line_full.astype(np.int32),
        "eid_honest": line_honest.astype(np.int32),
    })
    df.to_parquet(out_dir / "lines.parquet", index=False)
    _save_templates(out_dir / "templates_full.csv", t_full, line_full)
    _save_templates(out_dir / "templates_honest.csv", t_honest, line_honest)
    meta = {
        "dataset": "bgl", "lines": int(n), "anomalous_lines": int(df["is_anom"].sum()),
        "masked_strings": len(uniq), "templates_full": len(t_full),
        "templates_honest_train": sum(e < NOVEL_BASE for e in t_honest),
        "templates_novel_test": sum(e >= NOVEL_BASE for e in t_honest),
        "boundary_line": boundary, "train_frac": train_frac, "sim_th": sim_th,
        "read_mask_seconds": round(read_s, 1), "drain_seconds": round(drain_s, 2),
        "lines_per_sec_end_to_end": round(n / (read_s + drain_s)),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta, indent=2))
    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", choices=["hdfs", "bgl"], required=True)
    ap.add_argument("--sim-th", type=float, default=0.5)
    ap.add_argument("--limit", type=int, default=None, help="parse only the first N lines")
    args = ap.parse_args()
    fn = parse_hdfs if args.dataset == "hdfs" else parse_bgl
    fn(sim_th=args.sim_th, limit=args.limit)


if __name__ == "__main__":
    main()
