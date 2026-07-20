"""Pinned indicators — swings + fib confirmation lag (spec section 14, test 18)."""
import pandas as pd

from indicators.fib import fib_extension, fib_retracement, pullback_to_fib
from indicators.swings import swing_pivots


def _peak_at(pos, n=90):
    # a clean single peak at index `pos`
    close = [100 + min(i, 2 * pos - i) * 0.5 for i in range(n)]
    return pd.DataFrame({"open": close, "high": [c + 1 for c in close],
                         "low": [c - 1 for c in close], "close": close,
                         "volume": [1000] * n})


def test_fib_math():
    assert fib_retracement(100, 200, 382) == 161.8      # 38.2% down from high
    assert fib_retracement(100, 200, 618) == 138.2
    assert fib_extension(100, 200, 1272) == 227.2       # 1.272 projection


def test_pivot_confirmation_lag_no_lookahead():
    df = _peak_at(40)                                    # peak forms at bar 40
    n = 5
    # as-of bar 44 the peak (confirmed at 40+5=45) is NOT yet visible
    highs_44, _ = swing_pivots(df, n, as_of=44)
    assert 40 not in [p for p, _ in highs_44]
    # as-of bar 45 it is confirmed
    highs_45, _ = swing_pivots(df, n, as_of=45)
    assert 40 in [p for p, _ in highs_45]


def test_as_of_is_independent_of_future_data():
    # pivots as-of t must be identical whether or not later bars exist (no look-ahead)
    df = _peak_at(40, n=90)
    n = 5
    full = swing_pivots(df, n, as_of=50)
    truncated = swing_pivots(df.iloc[:60].reset_index(drop=True), n, as_of=50)
    assert full == truncated


def test_fib_level_stable_as_of_a_bar():
    df = _peak_at(40, n=90)
    # a fib level as-of bar 60 does not change when later data is appended
    lvl_a = pullback_to_fib(df, 5, 500, as_of=60)
    lvl_b = pullback_to_fib(df.iloc[:70].reset_index(drop=True), 5, 500, as_of=60)
    assert lvl_a == lvl_b
