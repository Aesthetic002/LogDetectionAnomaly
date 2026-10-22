"""The online detection pipeline: parse -> sessionize -> score -> store (note 02).

All detectors run side by side on the same stream so the comparison is fair (note 14):

    deeplog_vanilla   unseen = anomaly (P1), fixed top-g,  scored when the trace closes
    deeplog_matcher   semantic matcher (P4),   fixed top-g,  trace close     (ablation)
    deeplog_topp      P1,                      top-p,        trace close     (ablation)
    deeplog_both      P4,                      top-p,        trace close     (ablation)
    deeplog_full      P4,                      top-p,        step-wise       (ours)
    rf                Random Forest on the trace's event counts, trace close
    B1_keyword        ERROR|Exception|Traceback|timeout|failed, debounced per service
    B2_error_rate     share of non-2xx gateway responses in a sliding window
    B3_health         /health probe every 10 s, 3 consecutive failures
"""
from __future__ import annotations

import json
import os
import pickle
import sqlite3
import re
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import httpx
import numpy as np
import torch

from logpulse import store
from logpulse.features.vectorize import count_matrix
from logpulse.models.deeplog import DeepLog, step_stats
from logpulse.models.template_matcher import TemplateMatcher
from logpulse.online.parser import OnlineParser
from logpulse.online.sessionizer import TERMINAL_RE, Sessionizer, Trace
from logpulse.parsing.drain_parser import level_class
from logpulse.paths import PAD, UNSEEN

DEFAULTS = {
    "h": 10, "g": 9, "p": 0.95, "tau": 0.6,
    "reorder_delay": 2.0, "idle_timeout": 5.0,
    "b1_debounce": 10.0, "b2_window": 60.0, "b2_threshold": 0.05, "b2_min": 20,
    "b3_interval": 10.0, "b3_failures": 3,
}
B1_RE = re.compile(r"ERROR|Exception|Traceback|timeout|failed", re.I)
SESSION_CLOSE = {  # name -> (policy, rule)
    "deeplog_vanilla": ("P1", "topg"),
    "deeplog_matcher": ("P4", "topg"),
    "deeplog_topp": ("P1", "topp"),
    "deeplog_both": ("P4", "topp"),
}
MODEL_DETECTORS = list(SESSION_CLOSE) + ["deeplog_full", "rf"]
BASELINES = ["B1_keyword", "B2_error_rate", "B3_health"]


def parse_ts(s) -> float:
    if isinstance(s, (int, float)):
        return float(s)
    return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()


class Pipeline:
    def __init__(self, db_path: Path, art_dir: Path | None, mode: str = "detect", run: str = "run",
                 service_urls: dict | None = None):
        self.mode = mode
        self.run = run
        self.closed = False
        self.db_path = db_path
        self.con = store.connect(db_path)
        self.lock = threading.RLock()
        self.cfg = dict(DEFAULTS)
        self.model = self.rf = self.matcher = None
        self.version = {"model": "none", "templates": "none"}
        art_ok = art_dir is not None and (art_dir / "deeplog.pt").exists() and mode == "detect"
        self.parser = OnlineParser(art_dir if art_ok else None)
        if art_ok:
            cfg_file = art_dir / "config.json"
            if cfg_file.exists():
                self.cfg.update(json.loads(cfg_file.read_text()))
            self.model, ck = DeepLog.load(art_dir / "deeplog.pt")
            self.cfg["h"] = ck.get("h", self.cfg["h"])
            tm = json.loads((art_dir / "template_map.json").read_text())
            known = [(int(e), d["template"], s, lc) for e, d in tm["events"].items()
                     for s in d["services"] for lc in d["level_classes"]]
            self.matcher = TemplateMatcher(known, tau=self.cfg["tau"])
            if (art_dir / "rf.pkl").exists():
                self.rf = pickle.loads((art_dir / "rf.pkl").read_bytes())
            self.version = {"model": self.cfg.get("model_version", ck.get("version", "v1")),
                            "templates": tm.get("version", "v1")}
        self.sess = Sessionizer(self.cfg["reorder_delay"], self.cfg["idle_timeout"])
        self.templates: dict[int, dict] = {}
        self._dirty_templates: set[int] = set()
        # continue numbering if the detector restarts into an existing run file
        self.next_raw = (self.con.execute("SELECT MAX(id) FROM raw_lines").fetchone()[0] or 0) + 1
        self.next_event = (self.con.execute("SELECT MAX(id) FROM events").fetchone()[0] or 0) + 1
        self.line_no: dict[str, int] = {}
        self.inbox: deque = deque()
        self.stats = {"received": 0, "dropped": 0, "processed": 0, "started": time.time()}
        # baselines
        self.b1_last: dict[str, float] = {}
        self.b2_window: deque = deque()
        self.b2_last = 0.0
        self.b3_fail: dict[str, int] = {}
        self.b3_state: dict[str, str] = {}
        self.service_urls = service_urls or {}
        store.set_info(self.con, run=run, mode=mode, started=self.stats["started"], cfg=self.cfg,
                       version=self.version)

    # ------------------------------------------------------------ ingest
    def submit(self, records):
        if isinstance(records, dict):
            records = [records]
        self.inbox.append(records)
        self.stats["received"] += len(records)

    def tick(self):
        with self.lock:
            if self.closed:
                return
            now = time.time()
            batch = []
            while self.inbox:
                batch.extend(self.inbox.popleft())
            self._ingest(batch, now)
            released = self.sess.release(now)
            self._score_steps(released, now)
            self._close(self.sess.due(now), now)
            self._flush_templates()
            self.con.commit()

    def _ingest(self, records, now):
        raw_rows, ev_rows = [], []
        for r in records:
            msg = r.get("msg")
            if not msg:
                self.stats["dropped"] += 1
                continue
            ts = parse_ts(r.get("ts", now))
            service = r.get("service", "?")
            level = r.get("level", "INFO")
            tid = r.get("trace_id") or "-"
            container = str(r.get("container_name", service)).lstrip("/")
            n = self.line_no[container] = self.line_no.get(container, 0) + 1
            raw_id = self.next_raw
            self.next_raw += 1
            raw_rows.append((raw_id, ts, now, container, f"svc.{container}", n, service, level, tid, msg))

            eid, template = self.parser.parse(msg)
            t = self._template(eid, template, service, level, ts)
            unseen = 0 if self.parser.is_known(eid) else 1
            ev_rows.append((self.next_event, raw_id, ts, service, level, tid, eid, template, unseen,
                            t.get("matched_to"), t.get("match_score")))
            self.next_event += 1
            self.stats["processed"] += 1

            self._b1(service, level, msg, tid, ts, raw_id, now)
            if service == "gateway":
                self._b2(msg, ts, now)
            if tid != "-":
                self.sess.push({"ts": ts, "eid": eid, "raw_id": raw_id, "service": service, "level": level,
                                "template": template, "trace_id": tid, "msg": msg, "unseen": unseen})
        if raw_rows:
            self.con.executemany("INSERT INTO raw_lines VALUES (?,?,?,?,?,?,?,?,?,?)", raw_rows)
            self.con.executemany("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?)", ev_rows)

    def _template(self, eid, template, service, level, ts) -> dict:
        t = self.templates.get(eid)
        if t is None:
            known = self.parser.is_known(eid)
            t = self.templates[eid] = {"event_id": eid, "template": template, "service": service, "level": level,
                                       "count": 0, "first_seen": ts, "status": "known" if known else "new",
                                       "matched_to": None, "match_score": None}
            if not known:
                self._match(t)
        elif t["template"] != template:
            t["template"] = template
            if t["status"] != "known":
                self._match(t)
        t["count"] += 1
        self._dirty_templates.add(eid)
        return t

    def _match(self, t):
        if self.matcher is None:
            return
        mapped, score = self.matcher.match(t["template"], t["service"], level_class(t["level"]))
        t["matched_to"], t["match_score"] = mapped, round(float(score), 3)
        t["status"] = "new-matched" if mapped is not None else "new-unmatched"

    def _flush_templates(self):
        if not self._dirty_templates:
            return
        rows = [tuple(self.templates[e][k] for k in ("event_id", "template", "service", "level", "count",
                                                      "first_seen", "status", "matched_to", "match_score"))
                for e in self._dirty_templates]
        self.con.executemany("INSERT OR REPLACE INTO templates VALUES (?,?,?,?,?,?,?,?,?)", rows)
        self._dirty_templates.clear()

    # ------------------------------------------------------------ tokens
    def _tok_p1(self, ev) -> int:
        return ev["eid"] if self.parser.is_known(ev["eid"]) else UNSEEN

    def _tok_p4(self, ev) -> int | None:
        if self.parser.is_known(ev["eid"]):
            return ev["eid"]
        t = self.templates[ev["eid"]]
        if t.get("matched_to") is not None:
            return int(t["matched_to"])
        return UNSEEN if level_class(ev["level"]) == "error" else None  # None = neutral, skipped

    # ------------------------------------------------------------ step-wise scoring (ours)
    def _score_steps(self, released, now):
        batch = []
        for tr, ev in released:
            idx = len(tr.events)
            tr.events.append(ev)
            tr.p1.append(self._tok_p1(ev))
            if self.model is None:
                continue
            tok = self._tok_p4(ev)
            if tok is None:
                continue
            batch.append((tr, ev, idx, tok, list(tr.p4[-self.cfg["h"]:])))
            tr.p4.append(tok)
        if not batch:
            return
        h, p = self.cfg["h"], self.cfg["p"]
        V = self.model.n_events
        X = torch.tensor([[PAD] * (h - len(hist)) + [x if x < V else UNSEEN for x in hist] for *_, hist in batch])
        with torch.no_grad():
            probs = torch.softmax(self.model(X), dim=-1)
        sp, order = probs.sort(dim=1, descending=True)
        csum = sp.cumsum(1)
        dec_rows = []
        for i, (tr, ev, idx, tok, _) in enumerate(batch):
            pr = probs[i]
            pa = float(pr[tok]) if tok < V else 0.0
            greater = pr > pa
            rank = int(greater.sum()) + 1
            mass = float(pr[greater].sum())
            k = int((csum[i] < p).sum()) + 1
            top5 = [[int(order[i, j]), round(float(sp[i, j]), 4)] for j in range(min(5, V))]
            anomalous = tok == UNSEEN or mass >= p
            st = {"rank": rank, "mass": mass, "logp": float(np.log(max(pa, 1e-12))), "top5": top5, "k": k,
                  "event_idx": idx, "tok": tok}
            tr.p4_steps.append(st)
            dec_rows.append((tr.trace_id, idx, "deeplog_full", ev["eid"], pa, k, int(anomalous), json.dumps(top5),
                             json.dumps({"h": h, "p": p}), now))
            if anomalous and "deeplog_full" not in tr.alerted:
                reason = "unseen error template" if tok == UNSEEN else f"outside top-p set (p={p})"
                self._alert("deeplog_full", "model", now, tr, idx, top5, pa, reason)
        self.con.executemany("INSERT INTO decisions (trace_id, step, detector, event_id, p_actual, allowed_k, "
                             "anomalous, top5, params, ts) VALUES (?,?,?,?,?,?,?,?,?,?)", dec_rows)

    # ------------------------------------------------------------ session-close scoring
    def _close(self, traces: list[Trace], now):
        if not traces:
            return
        rows = [(tr.trace_id, tr.start_ts, tr.last_ts, len(tr.events), ",".join(sorted(tr.services)),
                 ",".join(sorted(tr.called)), now, tr.status) for tr in traces]
        self.con.executemany("INSERT OR REPLACE INTO sessions VALUES (?,?,?,?,?,?,?,?)", rows)
        if self.model is None:
            return
        h, g, p = self.cfg["h"], self.cfg["g"], self.cfg["p"]
        st = step_stats(self.model, [np.array(tr.p1) for tr in traces], h)
        bad_g = st.first_bad(st.steps_topg(g))
        bad_p = st.first_bad(st.steps_topp(p))
        for i, tr in enumerate(traces):
            for name, bad in (("deeplog_vanilla", bad_g[i]), ("deeplog_topp", bad_p[i])):
                if bad >= 0 and name not in tr.alerted:
                    tok = tr.p1[bad]
                    reason = "unseen template" if tok == UNSEEN else (
                        f"outside top-g set (g={g})" if name == "deeplog_vanilla" else f"outside top-p set (p={p})")
                    top5, pa = self._expected(tr.p1[max(0, bad - h):bad], tok)
                    self._alert(name, "model", now, tr, bad, top5, pa, reason)
            for name, rule in (("deeplog_matcher", "topg"), ("deeplog_both", "topp")):
                if name in tr.alerted:
                    continue
                for s in tr.p4_steps:
                    hit = s["tok"] == UNSEEN or (s["rank"] > g if rule == "topg" else s["mass"] >= p)
                    if hit:
                        reason = "unseen error template" if s["tok"] == UNSEEN else (
                            f"outside top-g set (g={g})" if rule == "topg" else f"outside top-p set (p={p})")
                        self._alert(name, "model", now, tr, s["event_idx"], s["top5"], float(np.exp(s["logp"])), reason)
                        break
        if self.rf is not None:
            X = count_matrix([np.array(tr.p1) for tr in traces], self.model.n_events)
            pred = self.rf.predict(X)
            for tr, yhat in zip(traces, pred):
                if yhat and "rf" not in tr.alerted:
                    self._alert("rf", "model", now, tr, len(tr.events) - 1, [], None, "RF: anomalous event counts")

    def _expected(self, hist, tok):
        h, V = self.cfg["h"], self.model.n_events
        x = torch.tensor([[PAD] * (h - len(hist)) + [e if e < V else UNSEEN for e in hist]])
        with torch.no_grad():
            pr = torch.softmax(self.model(x), dim=-1)[0]
        sp, order = pr.sort(descending=True)
        top5 = [[int(order[j]), round(float(sp[j]), 4)] for j in range(min(5, V))]
        return top5, float(pr[tok]) if tok < V else 0.0

    # ------------------------------------------------------------ baselines
    def _b1(self, service, level, msg, tid, ts, raw_id, now):
        if not (B1_RE.search(level) or B1_RE.search(msg)):
            return
        if now - self.b1_last.get(service, -1e9) < self.cfg["b1_debounce"]:
            return
        self.b1_last[service] = now
        self._insert_alert("B1_keyword", "baseline", now, ts, tid, service, None, None, None, msg,
                           None, "keyword match", raw_id)

    def _b2(self, msg, ts, now):
        m = TERMINAL_RE.match(msg)
        if not m:
            return
        w = self.b2_window
        w.append((ts, int(m.group(1)) // 100 != 2))
        while w and w[0][0] < ts - self.cfg["b2_window"]:
            w.popleft()
        n = len(w)
        errs = sum(e for _, e in w)
        if n >= self.cfg["b2_min"] and errs / n > self.cfg["b2_threshold"] and now - self.b2_last >= self.cfg["b2_window"]:
            self.b2_last = now
            self._insert_alert("B2_error_rate", "baseline", now, ts, None, "gateway", None, None, None, None, None,
                               f"error rate {errs}/{n} = {errs / n:.1%} in {self.cfg['b2_window']:.0f}s", None)

    def probe_health(self):
        """B3 — called every b3_interval seconds from its own thread."""
        now = time.time()
        for svc, url in self.service_urls.items():
            try:
                ok = httpx.get(f"{url}/health", timeout=2.0).status_code == 200
            except httpx.HTTPError:
                ok = False
            with self.lock:
                self.b3_fail[svc] = 0 if ok else self.b3_fail.get(svc, 0) + 1
                if ok:
                    self.b3_state[svc] = "up"
                elif self.b3_fail[svc] >= self.cfg["b3_failures"] and self.b3_state.get(svc) != "down":
                    self.b3_state[svc] = "down"
                    self._insert_alert("B3_health", "baseline", now, now, None, svc, None, None, None, None, None,
                                       f"{self.b3_fail[svc]} consecutive health-check failures", None)
                    self.con.commit()

    # ------------------------------------------------------------ alerts
    def _alert(self, detector, kind, now, tr: Trace, idx, top5, p_obs, reason):
        tr.alerted.add(detector)
        ev = tr.events[idx]
        expected = [[e, pr, self.templates.get(e, {}).get("template", "")] for e, pr in top5]
        self._insert_alert(detector, kind, now, ev["ts"], tr.trace_id, ev["service"], idx, expected, ev["eid"],
                           ev["template"], p_obs, reason, ev["raw_id"])

    def _insert_alert(self, detector, kind, now, event_ts, tid, service, step, expected, observed, obs_template,
                      p_obs, reason, raw_ref):
        self.con.execute(
            "INSERT INTO alerts (detector, kind, ts, event_ts, trace_id, service, step, expected, observed, "
            "observed_template, p_observed, reason, raw_ref, model_version, template_version) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (detector, kind, now, event_ts, tid, service, step, json.dumps(expected) if expected is not None else None,
             observed, obs_template, p_obs, reason, raw_ref, self.version["model"], self.version["templates"]))

    def add_ground_truth(self, row: dict):
        with self.lock:
            self.con.execute("INSERT OR REPLACE INTO ground_truth VALUES (?,?,?,?,?,?,?)",
                             (row["fault_id"], row["type"], row["target_service"], row["start_ts"],
                              row.get("end_ts"), row.get("run_id", self.run), row.get("label", "")))
            self.con.commit()

    def export(self, dest: Path):
        """Consistent snapshot of the run DB (SQLite backup API) for host-side scoring."""
        with self.lock:
            self.con.commit()
            if Path(dest).resolve() == Path(self.db_path).resolve():
                return dest
            Path(dest).parent.mkdir(parents=True, exist_ok=True)
            tmp = Path(str(dest) + ".tmp")
            out = sqlite3.connect(tmp)
            self.con.backup(out)
            out.close()
            os.replace(tmp, dest)
            return dest

    def close(self, export_to: Path | None = None):
        with self.lock:
            if self.closed:
                return
            if export_to is not None:
                self.export(export_to)
            self.closed = True
            self.con.commit()
            self.con.close()
