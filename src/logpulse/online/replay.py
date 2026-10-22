"""Offline replay of a recorded live run with the frozen artifacts.

Re-parses the run's raw lines in arrival order with the frozen Drain tree (exactly what
the online parser does), rebuilds traces and the P1 / P4 token sequences. Used to train
(normal run), tune (seeds 1-3) and evaluate the decision rules on the demo app (E11 demo).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from logpulse import store
from logpulse.models.template_matcher import TemplateMatcher
from logpulse.online.parser import OnlineParser
from logpulse.parsing.drain_parser import level_class
from logpulse.paths import RUNS, UNSEEN


def load_raw(run: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    con = store.connect(RUNS / f"{run}.db", readonly=True)
    raw = pd.read_sql_query("SELECT id, ts, received_at, service, level, trace_id, msg FROM raw_lines ORDER BY id", con)
    gt = pd.read_sql_query("SELECT * FROM ground_truth", con)
    sessions = pd.read_sql_query("SELECT * FROM sessions", con)
    con.close()
    return raw, gt, sessions


@dataclass
class Replay:
    traces: pd.DataFrame          # trace_id, start_ts, p1, p4, services, called, statements
    templates: dict               # eid -> dict(template, service, level, known, best, best_score)
    raw: pd.DataFrame


def replay(run: str, art_dir: Path, tau: float | None = None) -> Replay:
    raw, _, _ = load_raw(run)
    parser = OnlineParser(art_dir)
    tm = json.loads((art_dir / "template_map.json").read_text())
    known = [(int(e), d["template"], s, lc) for e, d in tm["events"].items()
             for s in d["services"] for lc in d["level_classes"]]
    matcher = TemplateMatcher(known, tau=0.0)
    eids, tpls = [], []
    for m in raw["msg"]:
        e, t = parser.parse(m)
        eids.append(e)
        tpls.append(t)
    raw = raw.assign(eid=eids, template=tpls)
    templates = {}
    for e, g in raw.groupby("eid"):
        first = g.iloc[0]
        d = {"template": g["template"].iloc[-1], "service": first["service"], "level": first["level"],
             "known": parser.is_known(int(e)), "count": len(g)}
        if not d["known"]:
            best, score = matcher.match(d["template"], d["service"], level_class(d["level"]))
            d["best"], d["best_score"] = best, score
        templates[int(e)] = d
    return Replay(build_traces(raw, templates, tau), templates, raw)


def p4_token(eid, level, templates, tau):
    t = templates[eid]
    if t["known"]:
        return eid
    if tau is not None and t.get("best") is not None and t["best_score"] >= tau:
        return int(t["best"])
    return UNSEEN if level_class(level) == "error" else None


def build_traces(raw: pd.DataFrame, templates: dict, tau: float | None) -> pd.DataFrame:
    ev = raw[raw["trace_id"].notna() & (raw["trace_id"] != "-")].sort_values(["trace_id", "ts", "id"], kind="stable")
    rows = []
    for tid, g in ev.groupby("trace_id", sort=False):
        e = g["eid"].to_numpy()
        p1 = np.array([x if templates[x]["known"] else UNSEEN for x in e])
        p4 = [p4_token(x, lv, templates, tau) for x, lv in zip(e, g["level"])]
        called = set(g["msg"].str.extract(r"^Calling (\w+)")[0].dropna())
        rows.append((tid, float(g["ts"].iloc[0]), p1, np.array([x for x in p4 if x is not None], dtype=np.int64),
                     set(g["service"]), called))
    return pd.DataFrame(rows, columns=["trace_id", "start_ts", "p1", "p4", "services", "called"])


def as_sessions(tr: pd.DataFrame) -> pd.DataFrame:
    """Shape expected by eval.live.trace_labels."""
    return pd.DataFrame({"trace_id": tr["trace_id"], "start_ts": tr["start_ts"],
                         "services": [",".join(sorted(s)) for s in tr["services"]],
                         "called": [",".join(sorted(s)) for s in tr["called"]]})
