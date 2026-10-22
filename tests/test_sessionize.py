import numpy as np
import pandas as pd

from logpulse.eval import live
from logpulse.eval.splits import chronological, random_split
from logpulse.features.sessionize import trace_sessions
from logpulse.features.vectorize import Featurizer, count_matrix
from logpulse.online.sessionizer import Sessionizer
from logpulse.paths import NOVEL_BASE, UNSEEN


def test_trace_sessions_orders_by_time():
    ev = pd.DataFrame({"trace_id": ["a", "b", "a", "a", "-"], "ts": [3.0, 1.0, 1.0, 2.0, 0.0],
                       "seq": [0, 1, 2, 3, 4], "service": ["x", "y", "x", "z", "x"], "event_id": [7, 5, 2, 3, 9]})
    s = trace_sessions(ev).set_index("trace_id")
    assert list(s.loc["a", "events"]) == [2, 3, 7]
    assert "-" not in s.index


def test_live_sessionizer_reorders_and_closes():
    s = Sessionizer(delay=1.0, idle=5.0)
    for ts, msg, svc in [(10.2, "Created order 1 for user 2", "orders"), (10.0, "Checkout request", "gateway"),
                         (10.5, "Response sent with status 200 in 5 ms", "gateway")]:
        s.push({"ts": ts, "trace_id": "t1", "msg": msg, "service": svc, "eid": 2})
    out = s.release(now=12.0)
    assert [ev["ts"] for _, ev in out] == [10.0, 10.2, 10.5]
    closed = s.due(now=12.0)
    assert len(closed) == 1 and closed[0].status == 200
    # a late event re-opens the trace
    s.push({"ts": 11.0, "trace_id": "t1", "msg": "Payment confirmed", "service": "payment", "eid": 3})
    assert s.release(now=13.0)[0][0].trace_id == "t1" and "t1" in s.open


def test_count_matrix_maps_novel_to_unseen():
    X = count_matrix([np.array([2, 2, 3]), np.array([NOVEL_BASE + 4, 2])], n_events=5)
    assert X[0, 2] == 2 and X[0, 3] == 1
    assert X[1, UNSEEN] == 1 and X[1, 2] == 1
    assert Featurizer("binary").fit(X).transform(X)[0, 2] == 1


def test_chronological_split_no_future_in_train():
    t = np.array([5, 1, 4, 2, 3, 9, 8, 7, 6, 0])
    tr, va, te = chronological(t, train=0.8, val_of_train=0.25)
    assert t[np.concatenate([tr, va])].max() < t[te].min()
    assert len(set(tr) | set(va) | set(te)) == 10
    a, b, c = random_split(10, seed=1)
    assert len(set(a) | set(b) | set(c)) == 10


def test_alert_mapping_and_labels():
    gt = pd.DataFrame([{"fault_id": "f1", "type": "F3_skip_reserve", "target_service": "orders",
                        "start_ts": 100.0, "end_ts": 160.0}])
    sessions = pd.DataFrame({"trace_id": ["a", "b", "c"], "start_ts": [110.0, 50.0, 300.0],
                             "services": ["gateway,orders", "gateway,orders", "gateway"], "called": ["", "", ""]})
    alerts = pd.DataFrame({"detector": ["m", "m", "m"], "ts": [112.0, 55.0, 400.0], "trace_id": ["a", "b", "c"],
                           "service": ["orders", "orders", "gateway"]})
    m = live.map_alerts(alerts, gt, sessions)
    assert list(m["fault_id"].fillna("-")) == ["f1", "-", "-"]
    det = live.detection_table(m, gt, ["m"])
    assert det["detected"].iloc[0] and abs(det["ttd"].iloc[0] - 12.0) < 1e-9
    y = live.trace_labels(sessions, gt)
    assert y["a"] == 1 and y["b"] == 0 and y["c"] == 0
