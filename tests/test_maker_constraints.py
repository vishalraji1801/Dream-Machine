"""Strategy Maker — Commit 3: generation-time rejects (test 3)."""
from maker.constraints import check, estimate_edge_pct, round_trip_cost_pct
from maker.grammar import make_candidate


def _cand(direction="long", exit_block=("atr_trail", {"mult": 5, "period": 14})):
    return make_candidate(direction, {
        "setup": ("nday_extreme", {"lookback": 100, "side": "high"}),
        "trigger": ("breakout_close", {"of": "setup_level"}),
        "exit": exit_block,
    })


def test_delivery_cost_is_about_a_quarter_percent():
    assert 0.20 < round_trip_cost_pct("delivery") < 0.30       # ~0.24%
    assert round_trip_cost_pct("intraday") < round_trip_cost_pct("delivery")


def test_normal_swing_candidate_passes():
    ok, reason, detail = check(_cand(), product="delivery")
    assert ok and reason == "ok"
    assert detail["est_edge_pct"] > detail["required_gross_pct"]


def test_short_on_cnc_is_rejected():
    ok, reason, _ = check(_cand(direction="short"), product="delivery")
    assert not ok and reason == "short_on_cnc"


def test_duplicate_is_rejected():
    c = _cand()
    ok, reason, _ = check(c, product="delivery", seen_cids=[c.cid])
    assert not ok and reason == "duplicate"


def test_turnover_budget_rejects_with_cost_math():
    # crank the cost multiple so the required gross exceeds the estimated edge; the
    # trial detail must carry the cost math that justified the kill.
    c = _cand(exit_block=("r_multiple", {"r": 1.5}))
    ok, reason, detail = check(c, product="delivery", cost_multiple_min=20.0)
    assert not ok and reason == "turnover_budget"
    assert detail["required_gross_pct"] > detail["est_edge_pct"]
    assert detail["round_trip_cost_pct"] > 0
