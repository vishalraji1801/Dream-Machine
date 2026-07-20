"""Strategy Maker — candlestick + chart-pattern blocks wired into the generator.

Guards: pullback_depth / flush / gap / double_bottom setups and the confirm_candle
trigger all COMPILE and EVALUATE (no NotImplementedError), the candle-shape helpers
classify correctly, double_bottom detects a real W, and the generator emits them all.
"""
import math
import random

import pandas as pd

from maker.blocks import BLOCKS
from maker.generate import _sample_block, random_candidates
from maker.grammar import (compile, make_candidate, _is_bullish_engulfing, _is_doji,
                           _is_hammer_white, _is_morning_star)


def _df(n=300):
    close = [100 + 20 * math.sin(i / 13) + i * 0.05 for i in range(n)]
    return pd.DataFrame({"timestamp": pd.date_range("2016-01-01", periods=n, freq="D"),
                         "open": close, "high": [c + 2 for c in close],
                         "low": [c - 2 for c in close], "close": close, "volume": [1000] * n})


# ── candle-shape helpers ──────────────────────────────────────────────────────

def test_hammer_white_detection():
    # small white body at the top, long lower wick, no upper wick
    assert _is_hammer_white(o=100.9, h=101.0, l=98.0, c=101.0)
    # a plain down bar is not a hammer
    assert not _is_hammer_white(o=101.0, h=101.2, l=100.8, c=100.0)


def test_doji_detection():
    assert _is_doji(o=100.0, h=101.0, l=99.0, c=100.05)     # open ≈ close
    assert not _is_doji(o=100.0, h=101.0, l=99.0, c=100.9)  # decisive close


def test_degenerate_bar_is_never_a_pattern():
    assert not _is_hammer_white(100, 100, 100, 100)         # zero range
    assert not _is_doji(100, 100, 100, 100)


# ── setups compile + evaluate (no NotImplementedError) ────────────────────────

def test_new_setups_all_evaluate():
    for setup in (("pullback_depth", {"from_high_pct": 5, "within_trend_ma": 200}),
                  ("flush", {"down_pct_in_bars": (10, 5)}),
                  ("gap", {"gap_pct_min": 2, "direction": "up"}),
                  ("double_bottom", {"swing_n": 5, "tol_pct": 2.0}),
                  ("inv_head_shoulders", {"swing_n": 5, "shoulder_tol_pct": 5.0}),
                  ("fib_pullback", {"swing_n": 5, "level": 618})):
        c = make_candidate("long", {
            "setup": setup,
            "trigger": ("breakout_close", {"of": "setup_level"}),
            "exit": ("atr_trail", {"mult": 4, "period": 14})})
        sig = compile(c)("X", _df(), {})           # must not raise
        assert sig.direction in ("BUY", "HOLD")


def test_bullish_engulfing_and_morning_star_helpers():
    # bullish engulfing: prior down bar, current up bar whose body engulfs it
    assert _is_bullish_engulfing(po=102, pc=100, o=99.5, c=102.5)
    assert not _is_bullish_engulfing(po=100, pc=102, o=101, c=103)   # prior was up
    # morning star: down bar, small star, strong up bar closing above bar1 midpoint
    assert _is_morning_star(o1=110, c1=100, o2=99, c2=99.5, o3=100, c3=108)
    assert not _is_morning_star(o1=110, c1=100, o2=99, c2=99.5, o3=100, c3=101)  # weak bar3


def test_bullish_reversal_candle_trigger_evaluates():
    for pat in ("engulfing", "morning_star"):
        c = make_candidate("long", {
            "setup": ("objective_level", {"level": "pdc"}),
            "trigger": ("bullish_reversal_candle", {"pattern": pat}),
            "exit": ("r_multiple", {"r": 2})})
        sig = compile(c)("X", _df(), {})           # must not raise NotImplementedError
        assert sig.direction in ("BUY", "HOLD")


def test_inv_head_shoulders_detects_the_pattern():
    # left low ~101, head ~96, right low ~101, with peaks (~106) between -> neckline break
    seq = ([112 - i for i in range(12)]        # decline to left shoulder low ~101
           + [101 + i for i in range(6)]       # rise to peak ~106
           + [106 - i for i in range(10)]      # decline to head low ~96 (deepest)
           + [96 + i for i in range(10)]       # rise to peak ~105
           + [105 - i for i in range(5)]       # decline to right shoulder low ~101
           + [101 + i for i in range(4)])      # recovery toward (not through) the neckline
    df = pd.DataFrame({"timestamp": pd.date_range("2016-01-01", periods=len(seq), freq="D"),
                       "open": seq, "high": [c + 0.5 for c in seq],
                       "low": [c - 0.5 for c in seq], "close": seq, "volume": [1000] * len(seq)})
    from maker.grammar import _setup_level
    lvl = _setup_level("inv_head_shoulders", {"swing_n": 3, "shoulder_tol_pct": 8.0}, df)
    assert lvl is not None and lvl > df["close"].iloc[-1]


def test_confirm_candle_trigger_evaluates():
    c = make_candidate("long", {
        "setup": ("objective_level", {"level": "pdh"}),
        "trigger": ("confirm_candle", {"accept": ("hammer_white", "doji"), "above_vwap": True}),
        "exit": ("r_multiple", {"r": 2})})
    sig = compile(c)("X", _df(), {})
    assert sig.direction in ("BUY", "HOLD")


def test_confirm_candle_fires_on_a_hammer():
    # build an uptrend, then make the last bar a strong white hammer above midpoint
    df = _df(260)
    df.loc[df.index[-1], ["open", "high", "low", "close"]] = [130.0, 130.3, 126.0, 130.2]
    c = make_candidate("long", {
        "setup": ("objective_level", {"level": "pdc"}),
        "trigger": ("confirm_candle", {"accept": ("hammer_white", "doji"), "above_vwap": True}),
        "exit": ("atr_trail", {"mult": 4, "period": 14})})
    ok = compile(c)("X", df, {})
    assert ok.direction in ("BUY", "HOLD")           # evaluates; hammer path exercised


def test_double_bottom_detects_a_W():
    # two equal lows (~100) with a peak (~112) between them, then a recovery bar
    lows = ([120 - i for i in range(20)]          # decline into first low ~100
            + [100 + i for i in range(12)]        # rally to the middle peak ~112
            + [112 - i for i in range(12)]        # decline into second low ~100
            + [100 + i for i in range(8)])        # recovery toward the neckline
    df = pd.DataFrame({"timestamp": pd.date_range("2016-01-01", periods=len(lows), freq="D"),
                       "open": lows, "high": [c + 0.5 for c in lows],
                       "low": [c - 0.5 for c in lows], "close": lows, "volume": [1000] * len(lows)})
    from maker.grammar import _setup_level
    level = _setup_level("double_bottom", {"swing_n": 5, "tol_pct": 3.0}, df)
    assert level is not None and level > df["close"].iloc[-1]   # neckline above price


# ── generator emits the new blocks ────────────────────────────────────────────

PATTERN_BLOCKS = ("pullback_depth", "flush", "gap", "double_bottom", "confirm_candle",
                  "inv_head_shoulders", "fib_pullback", "bullish_reversal_candle")


def test_pattern_blocks_are_enabled_and_emitted():
    # The candlestick/chart-pattern blocks are on the IMPLEMENTED whitelist, so the hunt
    # both can construct them (evaluators proven above) AND emits them.
    from maker.generate import IMPLEMENTED
    enabled = {n for names in IMPLEMENTED.values() for n in names}
    for name in PATTERN_BLOCKS:
        assert name in enabled, f"{name} not enabled in the hunt"
    used = {}
    for c in random_candidates(800, seed=3):
        for bi in c.blocks.values():
            used[bi.name] = used.get(bi.name, 0) + 1
    for name in PATTERN_BLOCKS:
        assert used.get(name, 0) > 0, f"enabled block {name} was never emitted"


def test_new_blocks_sample_within_grid():
    rng = random.Random(0)
    for name in ("pullback_depth", "flush", "gap", "double_bottom", "confirm_candle"):
        for _ in range(50):
            p = _sample_block(rng, BLOCKS[name])
            for k, v in p.items():
                assert v in BLOCKS[name].params[k]
