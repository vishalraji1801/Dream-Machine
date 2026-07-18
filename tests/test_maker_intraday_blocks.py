"""Strategy Maker — Commit 11: intraday jars + mandatory square_off (tests 11-12)."""
import pytest

from maker.blocks import blocks_for_slot
from maker.constraints import check, effective_cost_pct, round_trip_cost_pct
from maker.grammar import make_candidate


def _intraday(hold=("square_off", {"at": "15:10"})):
    blocks = {"setup": ("opening_range", {"window_min": 15, "break_side": "high"}),
              "trigger": ("candle_confirm_1m", {"accept": ("hammer_white", "doji"), "above_vwap": True}),
              "exit": ("r_multiple", {"r": 2})}
    if hold:
        blocks["hold"] = hold
    return make_candidate("long", blocks, sleeve="intraday")


def test_intraday_jars_are_sleeve_scoped():
    intraday_setups = {b.name for b in blocks_for_slot("setup", sleeve="intraday")}
    swing_setups = {b.name for b in blocks_for_slot("setup", sleeve="swing")}
    assert "opening_range" in intraday_setups and "opening_range" not in swing_setups
    assert "nday_extreme" in swing_setups


def test_intraday_without_square_off_is_impossible():          # test 11
    with pytest.raises(ValueError):
        _intraday(hold=None)
    with pytest.raises(ValueError):
        _intraday(hold=("max_hold_min", {"max": 60}))          # not square_off -> rejected


def test_intraday_with_square_off_constructs():
    c = _intraday()
    assert c.sleeve == "intraday" and c.blocks["hold"].name == "square_off"


def test_swing_cannot_use_intraday_blocks():
    with pytest.raises(ValueError):
        make_candidate("long", {"setup": ("opening_range", {"window_min": 15, "break_side": "high"}),
                                "trigger": ("breakout_close", {"of": "setup_level"}),
                                "exit": ("r_multiple", {"r": 2})}, sleeve="swing")


def test_intraday_turnover_budget_includes_slippage():         # test 12
    assert effective_cost_pct("intraday") > round_trip_cost_pct("intraday")   # slippage folded in
    assert effective_cost_pct("delivery") == round_trip_cost_pct("delivery")  # swing: no add
    # force the reject and prove the slippage-inclusive cost math is on the trial row
    c = _intraday(hold=("square_off", {"at": "15:10"}))
    ok, reason, detail = check(c, cost_multiple_min=20.0)
    assert not ok and reason == "turnover_budget"
    assert detail["effective_cost_pct"] > detail["round_trip_cost_pct"]
    assert abs(detail["required_gross_pct"] - 20.0 * detail["effective_cost_pct"]) < 0.02
