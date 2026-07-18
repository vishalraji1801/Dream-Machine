"""indicators/swings.py — swing pivots with confirmation lag (spec section 14.1).

An N-bar pivot is a bar whose high (low) is the extreme of N bars on EACH side.
CONFIRMATION LAG: a pivot at index i exists only at bar i+N — using it earlier is
look-ahead. swing_pivots(as_of=t) returns only pivots confirmed by bar t, reading no
data after t. Shared by fib and S/R. Grid: swing_n in {5, 10, 20}.
"""
import pandas as pd


def swing_pivots(df: pd.DataFrame, n: int, as_of: int = None) -> tuple[list, list]:
    """Confirmed pivots as-of bar `as_of` (default last). Returns (highs, lows), each
    a list of (index, price). A pivot at i is included only if i + n <= as_of."""
    as_of = len(df) - 1 if as_of is None else as_of
    h, low = df["high"].values, df["low"].values
    highs, lows = [], []
    for i in range(n, len(df) - n):
        if i + n > as_of:                      # not yet confirmed as-of this bar
            continue
        if h[i] == h[i - n:i + n + 1].max() and h[i] > h[i - 1]:
            highs.append((i, float(h[i])))
        if low[i] == low[i - n:i + n + 1].min() and low[i] < low[i - 1]:
            lows.append((i, float(low[i])))
    return highs, lows


def last_swing_pair(df: pd.DataFrame, n: int, as_of: int = None):
    """The most recent confirmed (low, high) swing pair as-of a bar, or None."""
    highs, lows = swing_pivots(df, n, as_of)
    if not highs or not lows:
        return None
    hi_pos, hi = highs[-1]
    prior_lows = [(p, v) for p, v in lows if p < hi_pos]
    if not prior_lows:
        return None
    lo_pos, lo = prior_lows[-1]
    return {"low_pos": lo_pos, "low": lo, "high_pos": hi_pos, "high": hi}
