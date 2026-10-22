"""Live trace buffering (note 02, component 7).

Fluent Bit flushes each container separately, so lines of one request can arrive out of
order. Events wait in a small reorder buffer and are released in timestamp order once
they are ``delay`` seconds old. A trace closes on its terminal event (the gateway's
"Response sent ..." line) or after ``idle`` seconds without new events. A late event for
a recently closed trace re-opens it, so nothing a fault produces after the response is lost.
"""
from __future__ import annotations

import heapq
import itertools
import re
from collections import OrderedDict
from dataclasses import dataclass, field

TERMINAL_RE = re.compile(r"^Response sent with status (\d+)")
CALL_RE = re.compile(r"^Calling (\w+)")


@dataclass
class Trace:
    trace_id: str
    start_ts: float
    last_ts: float = 0.0
    last_release: float = 0.0
    events: list = field(default_factory=list)       # dicts: ts, eid, raw_id, service, level, template, ...
    p1: list = field(default_factory=list)           # tokens under policy P1 (unseen -> UNSEEN)
    p4: list = field(default_factory=list)           # tokens under policy P4 (matcher), neutral dropped
    p4_steps: list = field(default_factory=list)     # per scored P4 step: dict(rank, mass, logp, top5, k, event_idx, tok)
    services: set = field(default_factory=set)
    called: set = field(default_factory=set)
    status: int | None = None
    terminal: bool = False
    alerted: set = field(default_factory=set)
    closed_at: float | None = None


class Sessionizer:
    def __init__(self, delay: float = 2.0, idle: float = 5.0, keep_closed: float = 120.0):
        self.delay, self.idle, self.keep_closed = delay, idle, keep_closed
        self._heap: list = []
        self._seq = itertools.count()
        self.open: dict[str, Trace] = {}
        self.closed: OrderedDict[str, Trace] = OrderedDict()

    def push(self, ev: dict):
        heapq.heappush(self._heap, (ev["ts"], next(self._seq), ev))

    def release(self, now: float) -> list[tuple[Trace, dict]]:
        """Pop events old enough to be in order; attach them to their (re-)opened trace."""
        out = []
        while self._heap and self._heap[0][0] <= now - self.delay:
            _, _, ev = heapq.heappop(self._heap)
            tid = ev["trace_id"]
            tr = self.open.get(tid)
            if tr is None:
                tr = self.closed.pop(tid, None)
                if tr is not None:
                    tr.closed_at = None
                else:
                    tr = Trace(tid, ev["ts"])
                self.open[tid] = tr
            tr.last_ts = max(tr.last_ts, ev["ts"])
            tr.last_release = now
            tr.services.add(ev["service"])
            m = CALL_RE.match(ev["msg"])
            if m:
                tr.called.add(m.group(1))
            t = TERMINAL_RE.match(ev["msg"])
            if t and ev["service"] == "gateway":
                tr.terminal, tr.status = True, int(t.group(1))
            out.append((tr, ev))
        return out

    def due(self, now: float) -> list[Trace]:
        """Traces to close now: terminal seen, or idle for too long."""
        done = [tr for tr in self.open.values()
                if tr.terminal or now - tr.last_release > self.idle]
        for tr in done:
            del self.open[tr.trace_id]
            tr.closed_at = now
            tr.terminal = False  # a late event may re-open it
            self.closed[tr.trace_id] = tr
        while self.closed and now - next(iter(self.closed.values())).closed_at > self.keep_closed:
            self.closed.popitem(last=False)
        return done
