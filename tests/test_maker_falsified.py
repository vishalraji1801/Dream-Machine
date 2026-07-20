"""Strategy Maker — Commit 14: prior_falsified_region guard (test 15)."""
from maker.constraints import check
from maker.grammar import make_candidate


def _intraday(with_stocks_in_play=False):
    blocks = {"setup": ("opening_range", {"window_min": 15, "break_side": "high"}),
              "trigger": ("candle_confirm_1m", {"accept": ("hammer_white", "doji"), "above_vwap": True}),
              "exit": ("r_multiple", {"r": 2}),
              "hold": ("square_off", {"at": "15:10"})}
    if with_stocks_in_play:
        blocks["regime"] = ("rvol_gate", {"min": 3})
    return make_candidate("long", blocks, sleeve="intraday")


def test_fixed_list_all_day_intraday_rejected_without_override():
    ok, reason, _ = check(_intraday(with_stocks_in_play=False))
    assert not ok and reason == "prior_falsified_region"


def test_override_flag_allows_the_falsified_region():
    ok, reason, _ = check(_intraday(with_stocks_in_play=False), allow_falsified_region=True)
    assert reason != "prior_falsified_region"


def test_stocks_in_play_block_passes_the_guard():
    ok, reason, _ = check(_intraday(with_stocks_in_play=True))
    assert reason != "prior_falsified_region"


def test_swing_is_never_in_the_falsified_region():
    sw = make_candidate("long", {"setup": ("nday_extreme", {"lookback": 100, "side": "high"}),
                                 "trigger": ("breakout_close", {"of": "setup_level"}),
                                 "exit": ("atr_trail", {"mult": 5, "period": 14})}, sleeve="swing")
    ok, reason, _ = check(sw)
    assert reason != "prior_falsified_region"
