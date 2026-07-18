"""indicators/fib.py — Fibonacci levels (Strategy Maker, spec section 14.2).

Retracements of the last confirmed swing pair (382/500/618) and extension targets for
no-overhead-resistance contexts (1272/1618/2000). Levels are computed from CONFIRMED
swing pivots only (indicators.swings), so they inherit the confirmation lag — a fib
level as-of bar t never uses a pivot confirmed after t.
"""
from indicators.swings import last_swing_pair


def fib_retracement(low: float, high: float, level: int) -> float:
    """Retracement of a low->high move. level in thousandths (382 -> 0.382)."""
    return high - (high - low) * (level / 1000.0)


def fib_extension(low: float, high: float, level: int) -> float:
    """Extension target of a low->high move. level in thousandths (1272 -> 1.272)."""
    return low + (high - low) * (level / 1000.0)


def pullback_to_fib(df, n: int, level: int, as_of: int = None):
    """The retracement price of the last confirmed swing pair as-of a bar, or None."""
    pair = last_swing_pair(df, n, as_of)
    if pair is None:
        return None
    return round(fib_retracement(pair["low"], pair["high"], level), 4)


def fib_extension_target(df, n: int, level: int, as_of: int = None):
    pair = last_swing_pair(df, n, as_of)
    if pair is None:
        return None
    return round(fib_extension(pair["low"], pair["high"], level), 4)
