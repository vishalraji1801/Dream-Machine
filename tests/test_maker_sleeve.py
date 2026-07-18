"""Strategy Maker — Commit 10: sleeve field + product dispatch + sleeve routing (test 16)."""
from maker.admission import is_tradeable, paper_book_for
from maker.constraints import check
from maker.grammar import make_candidate


def _blocks():
    return {"setup": ("nday_extreme", {"lookback": 100, "side": "high"}),
            "trigger": ("breakout_close", {"of": "setup_level"}),
            "exit": ("atr_trail", {"mult": 5, "period": 14})}


def test_sleeve_sets_product_and_timeframe():
    sw = make_candidate("long", _blocks(), sleeve="swing")
    assert sw.sleeve == "swing" and sw.product == "delivery" and sw.timeframe == "1d"
    it = make_candidate("long", _blocks(), sleeve="intraday")
    assert it.sleeve == "intraday" and it.product == "intraday" and it.timeframe == "15m"


def test_same_structure_different_sleeve_is_a_different_cid():
    sw = make_candidate("long", _blocks(), sleeve="swing")
    it = make_candidate("long", _blocks(), sleeve="intraday")
    assert sw.cid != it.cid


def test_constraints_use_candidate_product_by_default():
    # a short is fine intraday (MIS) but rejected on swing (CNC), without passing product
    it_short = make_candidate("short", _blocks(), sleeve="intraday")
    ok, reason, _ = check(it_short)
    assert ok or reason != "short_on_cnc"
    sw_short = make_candidate("short", _blocks(), sleeve="swing")
    ok2, reason2, _ = check(sw_short)
    assert not ok2 and reason2 == "short_on_cnc"


def test_alive_intraday_does_not_enter_swing_book():
    it = make_candidate("long", _blocks(), sleeve="intraday")
    sw = make_candidate("long", _blocks(), sleeve="swing")
    assert paper_book_for(it) == "intraday"
    assert paper_book_for(sw) == "swing"


def test_intraday_inert_while_sleeve_disabled():
    it = make_candidate("long", _blocks(), sleeve="intraday")
    sw = make_candidate("long", _blocks(), sleeve="swing")
    cfg = {"intraday": {"enabled": False}, "swing": {"enabled": True}}
    assert not is_tradeable(it, cfg)           # intraday parked while sleeve off
    assert is_tradeable(sw, cfg)               # swing trades
    assert is_tradeable(it, {"intraday": {"enabled": True}, "swing": {"enabled": True}})
