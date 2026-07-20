"""Strategy Maker — Commit 10: sleeve field + product dispatch + sleeve routing (test 16)."""
from maker.admission import is_tradeable, paper_book_for
from maker.constraints import check
from maker.grammar import make_candidate


def _swing_blocks():
    return {"setup": ("nday_extreme", {"lookback": 100, "side": "high"}),
            "trigger": ("breakout_close", {"of": "setup_level"}),
            "exit": ("atr_trail", {"mult": 5, "period": 14})}


def _intraday(direction="long"):
    # intraday-valid blocks + mandatory square_off hold
    return make_candidate(direction, {
        "setup": ("opening_range", {"window_min": 15, "break_side": "high"}),
        "trigger": ("candle_confirm_1m", {"accept": ("hammer_white", "doji"), "above_vwap": True}),
        "exit": ("r_multiple", {"r": 2}),
        "hold": ("square_off", {"at": "15:10"})}, sleeve="intraday")


def test_sleeve_sets_product_and_timeframe():
    sw = make_candidate("long", _swing_blocks(), sleeve="swing")
    assert sw.sleeve == "swing" and sw.product == "delivery" and sw.timeframe == "1d"
    it = _intraday()
    assert it.sleeve == "intraday" and it.product == "intraday" and it.timeframe == "15m"


def test_cid_includes_timeframe():
    a = make_candidate("long", _swing_blocks(), sleeve="swing", timeframe="1d")
    b = make_candidate("long", _swing_blocks(), sleeve="swing", timeframe="1w")
    assert a.cid != b.cid                       # same blocks, different TF -> different candidate


def test_constraints_use_candidate_product_by_default():
    # a short is fine intraday (MIS) but rejected on swing (CNC), without passing product
    ok, reason, _ = check(_intraday(direction="short"))
    assert ok or reason != "short_on_cnc"
    sw_short = make_candidate("short", _swing_blocks(), sleeve="swing")
    ok2, reason2, _ = check(sw_short)
    assert not ok2 and reason2 == "short_on_cnc"


def test_alive_intraday_does_not_enter_swing_book():
    assert paper_book_for(_intraday()) == "intraday"
    assert paper_book_for(make_candidate("long", _swing_blocks(), sleeve="swing")) == "swing"


def test_intraday_inert_while_sleeve_disabled():
    it, sw = _intraday(), make_candidate("long", _swing_blocks(), sleeve="swing")
    cfg = {"intraday": {"enabled": False}, "swing": {"enabled": True}}
    assert not is_tradeable(it, cfg)           # intraday parked while sleeve off
    assert is_tradeable(sw, cfg)               # swing trades
    assert is_tradeable(it, {"intraday": {"enabled": True}, "swing": {"enabled": True}})
