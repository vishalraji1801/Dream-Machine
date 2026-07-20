"""Strategy Maker — Commit 20: timeframe-coherence gate (test 19)."""
from maker.coherence import adjacent, coherence_verdict, is_tf_spike


def test_adjacency():
    assert adjacent("15m") == ["5m", "30m"]
    assert adjacent("1d") == ["60m", "1w"]
    assert adjacent("1m") == ["3m"]


def test_tf_spike_flagged():                               # test 19
    passed = {"5m": False, "15m": True, "30m": False}
    assert is_tf_spike("15m", passed) is True

    verdict = coherence_verdict(passed)
    assert verdict["15m"]["tf_spike"] is True
    assert verdict["15m"]["accepted"] is False             # spike not accepted


def test_not_a_spike_if_a_neighbour_also_passes():
    passed = {"5m": True, "15m": True, "30m": False}
    assert is_tf_spike("15m", passed) is False
    assert coherence_verdict(passed)["15m"]["accepted"] is True


def test_hypothesis_exempts_the_spike():
    passed = {"5m": False, "15m": True, "30m": False}
    assert is_tf_spike("15m", passed, has_hypothesis=True) is False
    assert coherence_verdict(passed, has_hypothesis=True)["15m"]["accepted"] is True


def test_needs_both_neighbours_evaluated():
    # only one adjacent TF evaluated -> cannot judge coherence -> not a spike
    assert is_tf_spike("15m", {"15m": True, "30m": False}) is False
