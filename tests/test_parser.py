from logpulse.online.demo_templates import V1_EQUIVALENT, statement_of
from logpulse.parsing.drain_parser import CachedMiner, grouping_accuracy, make_miner


def test_masking_and_template():
    m = make_miner(sim_th=0.5)
    r1 = m.add_log_message("Received block blk_-695 of size 67108864 from /10.251.42.84")
    r2 = m.add_log_message("Received block blk_123 of size 1024 from /10.0.0.1")
    assert r1["cluster_id"] == r2["cluster_id"]
    assert "<BLK>" in r2["template_mined"] and "<IP>" in r2["template_mined"]


def test_dry_run_threshold_lesson():
    """Note 04: 'logged in' vs 'logged out' merge at 0.4 but stay apart at 0.6."""
    lines = ["User alice logged in", "User bob logged in", "User bob logged out"]
    low = make_miner(sim_th=0.4, masking=False)
    ids_low = [low.add_log_message(x)["cluster_id"] for x in lines]
    high = make_miner(sim_th=0.6, masking=False)
    ids_high = [high.add_log_message(x)["cluster_id"] for x in lines]
    assert ids_low[1] == ids_low[2]
    assert ids_high[1] != ids_high[2]


def test_cached_miner_matches_streaming():
    msgs = [f"Created order {i} for user {i % 7}" for i in range(50)] + ["Order 5 completed"] * 5
    plain = make_miner(sim_th=0.5)
    a = [plain.add_log_message(x)["cluster_id"] for x in msgs]
    cm = CachedMiner(make_miner(sim_th=0.5))
    b = [cm.learn_masked(cm.mask(x)) for x in msgs]
    assert a == b


def test_match_does_not_learn():
    cm = CachedMiner(make_miner(sim_th=0.5))
    cm.learn_masked(cm.mask("Payment confirmed for order 1"))
    n = len(cm.templates())
    assert cm.match_masked(cm.mask("Payment confirmed for order 99")) is not None
    assert cm.match_masked(cm.mask("Ledger write failed code 503 for order 2")) is None
    assert len(cm.templates()) == n


def test_grouping_accuracy():
    assert grouping_accuracy([1, 1, 2, 2], ["a", "a", "b", "b"]) == 1.0
    assert grouping_accuracy([1, 1, 2, 2], ["a", "a", "a", "a"]) == 0.0
    assert grouping_accuracy([1, 1, 2, 3], ["a", "a", "b", "b"]) == 0.5


def test_demo_statement_oracle():
    assert statement_of("Payment successfully confirmed for order 12") == "P5v2"
    assert V1_EQUIVALENT["P5v2"] == "P5"
    assert statement_of("Charging card for order 7 amount 998.00") == "P1"
    assert statement_of("something unknown") == "?"
