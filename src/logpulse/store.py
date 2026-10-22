"""SQLite store for the online pipeline — one DB file per run (data/demo/runs/<run>.db).

Tables follow note 13 'Data each panel needs'. Every alert row carries enough to walk the
traceability chain back: raw line -> event -> session -> decision -> alert -> ground truth.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_lines (
    id INTEGER PRIMARY KEY, ts REAL, received_at REAL, container TEXT, capture_file TEXT,
    line_no INTEGER, service TEXT, level TEXT, trace_id TEXT, msg TEXT);
CREATE INDEX IF NOT EXISTS raw_trace ON raw_lines(trace_id);
CREATE INDEX IF NOT EXISTS raw_ts ON raw_lines(ts);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY, raw_id INTEGER, ts REAL, service TEXT, level TEXT, trace_id TEXT,
    event_id INTEGER, template TEXT, unseen INTEGER, matched_to INTEGER, match_score REAL);
CREATE INDEX IF NOT EXISTS ev_trace ON events(trace_id);
CREATE INDEX IF NOT EXISTS ev_ts ON events(ts);

CREATE TABLE IF NOT EXISTS templates (
    event_id INTEGER PRIMARY KEY, template TEXT, service TEXT, level TEXT, count INTEGER,
    first_seen REAL, status TEXT, matched_to INTEGER, match_score REAL);

CREATE TABLE IF NOT EXISTS sessions (
    trace_id TEXT PRIMARY KEY, start_ts REAL, end_ts REAL, n_events INTEGER, services TEXT,
    called TEXT, closed_at REAL, status_code INTEGER);
CREATE INDEX IF NOT EXISTS sess_start ON sessions(start_ts);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY, trace_id TEXT, step INTEGER, detector TEXT, event_id INTEGER,
    p_actual REAL, allowed_k INTEGER, anomalous INTEGER, top5 TEXT, params TEXT, ts REAL);
CREATE INDEX IF NOT EXISTS dec_trace ON decisions(trace_id);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY, detector TEXT, kind TEXT, ts REAL, event_ts REAL, trace_id TEXT,
    service TEXT, step INTEGER, expected TEXT, observed INTEGER, observed_template TEXT,
    p_observed REAL, reason TEXT, raw_ref INTEGER, model_version TEXT, template_version TEXT);
CREATE INDEX IF NOT EXISTS al_ts ON alerts(ts);
CREATE INDEX IF NOT EXISTS al_det ON alerts(detector);
CREATE VIEW IF NOT EXISTS baseline_alerts AS SELECT * FROM alerts WHERE kind = 'baseline';

CREATE TABLE IF NOT EXISTS ground_truth (
    fault_id TEXT PRIMARY KEY, type TEXT, target_service TEXT, start_ts REAL, end_ts REAL,
    run_id TEXT, label TEXT);

CREATE TABLE IF NOT EXISTS feedback (trace_id TEXT, ts REAL, note TEXT);
CREATE TABLE IF NOT EXISTS run_info (key TEXT PRIMARY KEY, value TEXT);
"""


def connect(path: Path | str, readonly: bool = False) -> sqlite3.Connection:
    path = Path(path)
    if readonly:
        con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, check_same_thread=False, timeout=10)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(path, check_same_thread=False, timeout=30)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        con.executescript(SCHEMA)
    con.row_factory = sqlite3.Row
    return con


def set_info(con, **kv):
    con.executemany("INSERT OR REPLACE INTO run_info VALUES (?, ?)",
                    [(k, json.dumps(v)) for k, v in kv.items()])
    con.commit()


def get_info(con) -> dict:
    try:
        return {r["key"]: json.loads(r["value"]) for r in con.execute("SELECT * FROM run_info")}
    except sqlite3.OperationalError:
        return {}
