"""Strategy Maker — vectorized screen wired as the campaign pre-filter.

Two guarantees:
  1. For the vectorizable breakout family, the fast screen is CONSERVATIVE vs the
     event-driven screen — a fast PASS never flatters the honest edge (no funnel poison).
  2. For every non-vectorizable candidate, fast_screen_candidate is byte-identical to
     the event-driven screen_candidate (pure fallback, no behavior change).
"""
import dataclasses
import math
import os

import pandas as pd
import pytest
import yaml

from maker.grammar import BlockInstance, make_candidate
from maker.screen import _vectorizable, fast_screen_candidate, screen_candidate


def _cfg():
    cfg = yaml.safe_load(open(os.path.join("config", "config.yaml")))
    cfg["strategy"]["regime_filter_enabled"] = False
    cfg["trading"]["entry_start_time"] = ""; cfg["trading"]["entry_end_time"] = ""
    cfg["costs"]["product"] = "delivery"
    return cfg


def _fx(seed, n=900):
    close = [100 + 20 * math.sin(i / (11 + seed)) + i * 0.05 for i in range(n)]
    return pd.DataFrame({"timestamp": pd.date_range("2016-01-01", periods=n, freq="D"),
                         "open": close, "high": [c + 1.5 for c in close],
                         "low": [c - 1.5 for c in close], "close": close,
                         "volume": [1000] * n})


def _breakout(lookback=50, r=2):
    return make_candidate("long", {
        "setup": ("nday_extreme", {"lookback": lookback, "side": "high"}),
        "trigger": ("breakout_close", {"of": "setup_level"}),
        "exit": ("r_multiple", {"r": r})})


def test_matcher_selects_only_the_breakout_family():
    assert _vectorizable(_breakout()) == {"lookback": 50, "r_mult": 2}
    # side=low is a different setup — not vectorizable
    low = make_candidate("long", {
        "setup": ("nday_extreme", {"lookback": 50, "side": "low"}),
        "trigger": ("breakout_close", {"of": "setup_level"}),
        "exit": ("r_multiple", {"r": 2})})
    assert _vectorizable(low) is None
    # a regime gate is not modelled by vscreen — must fall back. (A regime-gated breakout
    # is unconstructible within the 4-param budget, so inject the block directly to prove
    # the matcher's defensive check rather than route through make_candidate.)
    base = _breakout()
    gated = dataclasses.replace(
        base, blocks={**base.blocks,
                      "regime": BlockInstance("trend_side", {"ma": 100, "side": "above"})})
    assert _vectorizable(gated) is None


def _trend(seed, n=700):
    # a trending series with pullbacks so breakouts fire AND resolve under event replay
    close = [100 + 30 * math.sin(i / 17 + seed) + i * 0.15 for i in range(n)]
    return pd.DataFrame({"timestamp": pd.date_range("2016-01-01", periods=n, freq="D"),
                         "open": close, "high": [c + 2 for c in close],
                         "low": [c - 2 for c in close], "close": close,
                         "volume": [1000] * n})


@pytest.mark.parametrize("lookback,r", [(50, 2), (100, 2), (50, 3)])
def test_fast_screen_is_conservative_vs_event_driven(lookback, r):
    # pool several trending symbols so the event-driven replay clears the calibration floor
    candles = {f"S{s}": _trend(s) for s in range(4)}
    cand = _breakout(lookback, r)
    _, freason, fm = fast_screen_candidate(cand, candles, _cfg())    # default window
    assert freason.startswith("vec:")                       # took the vectorized path
    _, _, em = screen_candidate(cand, candles, _cfg())
    if em["trades"] < 5:
        pytest.skip("event-driven replay produced too few trades to calibrate")
    # the fast screen may only UNDERSTATE the edge — never flatter it
    assert fm["pf"] <= em["pf"] + 1e-9, f"fast pf {fm['pf']} > event pf {em['pf']}"


def test_default_window_clears_the_compile_floor():
    """Regression: the maker default WINDOW must exceed the compiled fn's 210-bar warmup
    floor. Below it every candidate holds forever -> 0 trades -> the whole funnel is
    silently dead (the bug that made the event-driven screen/gauntlet/reserve inert)."""
    from maker.screen import WINDOW
    assert WINDOW >= 210
    # a trending series so breakouts actually fire and resolve under event-driven replay
    def trend(seed, n=700):
        close = [100 + 30 * math.sin(i / 17 + seed) + i * 0.15 for i in range(n)]
        return pd.DataFrame({"timestamp": pd.date_range("2016-01-01", periods=n, freq="D"),
                             "open": close, "high": [c + 2 for c in close],
                             "low": [c - 2 for c in close], "close": close,
                             "volume": [1000] * n})
    candles = {f"S{s}": trend(s) for s in range(4)}
    _, _, m = screen_candidate(_breakout(50, 2), candles, _cfg())   # default window
    assert m["trades"] > 0, "default window fell below the 210-bar floor -> dead funnel"


def test_non_vectorizable_falls_back_identically():
    candles = {"X": _fx(0), "Y": _fx(2)}
    cand = make_candidate("long", {
        "setup": ("nday_extreme", {"lookback": 50, "side": "low"}),
        "trigger": ("breakout_close", {"of": "setup_level"}),
        "exit": ("atr_trail", {"mult": 3, "period": 14})})
    assert _vectorizable(cand) is None
    fast = fast_screen_candidate(cand, candles, _cfg(), window=160)
    slow = screen_candidate(cand, candles, _cfg(), window=160)
    assert fast == slow                                     # pure fallback, no drift
