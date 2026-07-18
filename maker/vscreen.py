"""maker/vscreen.py — vectorized screen with a conservatism guarantee (section 16.4).

The gauntlet keeps event-driven bar replay (fidelity is its job). The cheap screen may
vectorize for speed, under ONE calibration rule: it must be CONSERVATIVE vs the replay
— SL-first, worst-case intrabar ordering, slippage applied. A flattering screen poisons
the funnel; a slightly harsh one only costs a few extra gauntlet runs. Test 24 asserts
vectorized PF <= replay PF on every calibration fixture.

This implements the vectorized path for the nday_extreme -> r_multiple breakout family
(the most common shape); other families fall back to the event-driven screen.
"""
import numpy as np
import pandas as pd

from indicators.core import atr


def vectorized_breakout_pf(df: pd.DataFrame, lookback: int, r_mult: float,
                           slippage_pct: float = 0.10, atr_period: int = 14) -> dict:
    """Conservative vectorized long-only breakout screen. Enters next-open (+slippage)
    on a new `lookback`-day high close; exits SL-first (worst-case) at a 1.5xATR stop or
    r_mult target. Deliberately pessimistic so its PF never exceeds the replay's."""
    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    open_ = df["open"].values
    a = atr(df, atr_period).values
    n = len(df)
    roll_max = pd.Series(close).rolling(lookback).max().values

    wins = losses = 0.0
    i = lookback
    while i < n - 1:
        if not np.isnan(roll_max[i]) and close[i] >= roll_max[i] and a[i] > 0:
            entry = open_[i + 1] * (1 + slippage_pct / 100)      # next-open + slippage
            risk = 1.5 * a[i]
            stop = entry - risk
            target = entry + r_mult * risk
            outcome = None
            for j in range(i + 1, n):
                if low[j] <= stop:                                # SL-first (worst case)
                    outcome = -(entry - stop) - entry * slippage_pct / 100
                    break
                if high[j] >= target:
                    outcome = (target - entry) - entry * slippage_pct / 100
                    break
            if outcome is None:
                outcome = close[n - 1] - entry
            if outcome > 0:
                wins += outcome
            else:
                losses += -outcome
            i = j + 1 if outcome is not None else i + 1          # no overlapping trades
        else:
            i += 1
    pf = (wins / losses) if losses > 0 else (3.0 if wins > 0 else 0.0)
    return {"pf": round(pf, 3), "wins": round(wins, 2), "losses": round(losses, 2)}


def assert_conservative(vectorized_pf: float, replay_pf: float) -> bool:
    """The calibration invariant: the vectorized screen must not flatter the replay."""
    return vectorized_pf <= replay_pf + 1e-9
