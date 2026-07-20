"""Strategy Maker — Commit 8: paper & portfolio admission (section 8)."""
from maker.admission import correlation_admission, swing_paper_gate


def test_swing_gate_passes_clean_paper():
    ok, reason = swing_paper_gate({"weeks": 10, "round_trips": 35, "pf": 1.5}, backtest_pf=1.7)
    assert ok and reason == "pass"


def test_swing_gate_fails_short_history():
    ok, reason = swing_paper_gate({"weeks": 4, "round_trips": 35, "pf": 1.5}, 1.6)
    assert not ok and reason == "insufficient_paper_history"


def test_swing_gate_fails_few_round_trips():
    ok, reason = swing_paper_gate({"weeks": 12, "round_trips": 12, "pf": 1.5}, 1.6)
    assert not ok and reason == "insufficient_round_trips"


def test_swing_gate_fails_low_paper_pf():
    ok, reason = swing_paper_gate({"weeks": 12, "round_trips": 35, "pf": 1.1}, 1.6)
    assert not ok and reason == "paper_pf_below_bar"


def test_swing_gate_fails_on_divergence():
    # paper PF 1.3 vs backtest 2.0 -> 35% divergence > 30%
    ok, reason = swing_paper_gate({"weeks": 12, "round_trips": 35, "pf": 1.3}, backtest_pf=2.0)
    assert not ok and reason == "paper_backtest_divergence"


def test_correlation_join_when_uncorrelated():
    cand = [1, -1, 1, -1, 1, -1, 1, -1]
    live = {"donchian": [1, 1, -1, -1, 1, 1, -1, -1]}     # corr 0 with cand
    action, detail = correlation_admission(cand, live)
    assert action == "join" and abs(detail["max_corr"]) < 0.7


def test_correlation_replace_when_correlated():
    cand = [1, -1, 2, -2, 1, -1, 2, -2]
    live = {"vcb": [1, -1, 2, -2, 1, -1, 2, -2]}          # identical -> corr 1
    action, detail = correlation_admission(cand, live)
    assert action == "replace" and detail["with"] == "vcb"


def test_correlation_join_when_no_live_strategies():
    action, _ = correlation_admission([1, -1, 1], {})
    assert action == "join"
