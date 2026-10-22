import numpy as np
import torch

from logpulse.models.deeplog import DeepLog, allowed_set, dedupe, step_stats, train, windows
from logpulse.models.template_matcher import TemplateMatcher, apply_policy
from logpulse.paths import PAD, UNSEEN


def test_windows_and_dedupe():
    X, y, owner = windows([np.array([2, 3, 4]), np.array([2, 3])], h=2)
    assert X.shape == (5, 2) and list(X[0]) == [PAD, PAD] and list(y) == [2, 3, 4, 2, 3]
    Xu, yu, w, inv = dedupe(X, y)
    assert w.sum() == 5 and len(yu) == 3
    assert np.array_equal(Xu[inv], X)


def test_model_shapes_and_learning():
    torch.manual_seed(0)
    seqs = [np.array([2, 3, 4, 5, 6])] * 200 + [np.array([2, 3, 7, 3, 4, 5, 6])] * 20
    m = DeepLog(8, emb=8, hidden=16, layers=1)
    assert m(torch.zeros(4, 3, dtype=torch.long)).shape == (4, 8)
    train(m, seqs, h=3, epochs=12, verbose=False, max_steps=80, bs=64)
    st = step_stats(m, [np.array([2, 3, 4, 5, 6]), np.array([2, 4, 3, 5, 6]), np.array([2, 3, UNSEEN])], h=3)
    pred_g = st.predict("topg", 1)
    assert not pred_g[0] and pred_g[1] and pred_g[2]
    assert st.first_bad(st.steps_topg(1))[2] == 2
    # top-p equivalence: allowed iff probability mass ranked above the actual event < p
    assert st.predict("topp", 0.9)[2]


def test_allowed_set_rules():
    p = torch.tensor([0.0, 0.0, 0.71, 0.22, 0.03, 0.003, 0.037])
    assert set(allowed_set(p, "topp", 0.95)) == {2, 3, 6}
    assert len(allowed_set(p, "topg", 5)) == 5


def test_matcher_and_policies():
    known = [(4, "Payment confirmed for order <NUM>", "payment", "info"),
             (3, "Charging card for order <NUM> amount <NUM>", "payment", "info"),
             (6, "Payment processor busy for order <NUM>, returning <NUM>", "payment", "error")]
    m = TemplateMatcher(known, tau=0.6)
    assert m.match("Payment successfully confirmed for order <NUM>", "payment", "info")[0] == 4
    assert m.match("Ledger write failed code <NUM> for order <NUM>", "payment", "error")[0] is None
    assert m.match("Payment successfully confirmed for order <NUM>", "orders", "info")[0] is None
    seq = np.array([2, 100, 101, 5])
    err = np.array([0, 0, 1, 0])
    assert list(apply_policy(seq, err, "P1", 10)) == [2, UNSEEN, UNSEEN, 5]
    assert list(apply_policy(seq, err, "P2", 10)) == [2, 5]
    assert list(apply_policy(seq, err, "P3", 10)) == [2, UNSEEN, 5]
    assert list(apply_policy(seq, err, "P4", 10, lambda i: 4 if i == 1 else None)) == [2, 4, UNSEEN, 5]
