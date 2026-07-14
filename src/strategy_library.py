"""
Strategy library — implementations mined from the YouTube strategy specs
(docs sources: Rayner Teo, Booming Bulls, Supertrend). Each is a pure
`fn(symbol, df, cfg) -> TradeSignal` reusing the toolkit in src/strategy.py and
registered into STRATEGY_REGISTRY.

ALL numeric parameters are UNVALIDATED sweep starting points — every strategy must
pass the validation gauntlet (walk-forward, plateau, 2x slippage, Monte Carlo,
paper) before capital. Nothing here is hardcoded as final; everything reads config.

Timeframes differ by strategy — feed the right candle series:
  - E-005 bb_mean_reversion : DAILY (swing, long-only)
  - E-003 donchian_trend_tsl: DAILY (positional, long+short)
  - E-001 supertrend        : intraday
  - E-008 orb_nifty         : intraday (needs a 'timestamp' column)
"""
from datetime import time as dtime

import pandas as pd

# NOTE: the strategy toolkit (TradeSignal, _atr, ...) lives in src.strategy, which
# imports THIS module to populate its registry. To avoid a circular import we pull
# the toolkit lazily inside each function (by call time, src.strategy is fully
# loaded), so strategy_library can be imported in any order.


def bb_mean_reversion(symbol: str, df: pd.DataFrame, cfg: dict):
    """Buy oversold pullbacks *within* an uptrend: above the long MA, closing
    below the lower Bollinger band; enter on a buy-limit below, exit at the mean."""
    from src.strategy import TradeSignal, _atr, _hold
    ma_period = cfg.get("bb_ma_period", 200)
    bb_period = cfg.get("bb_period", 20)
    bb_std = cfg.get("bb_std", 2.5)
    offset = cfg.get("bb_buy_limit_offset_pct", 3.0)
    atr_mult = cfg.get("bb_atr_stop_mult", 3.0)

    if len(df) < ma_period + 5:
        return _hold(symbol, "insufficient_data")
    close = df["close"]
    sma_trend = float(close.rolling(ma_period).mean().iloc[-1])
    mid = float(close.rolling(bb_period).mean().iloc[-1])
    sd = float(close.rolling(bb_period).std().iloc[-1])
    lower = mid - bb_std * sd
    last = float(close.iloc[-1])

    if last > sma_trend and last < lower:            # uptrend + oversold pullback
        entry = round(last * (1 - offset / 100), 2)  # buy-limit below the close
        atr = _atr(df, cfg.get("atr_period", 14))
        disaster = (round(min(sma_trend, entry - atr_mult * atr), 2)
                    if atr > 0 else round(entry * 0.9, 2))
        target = round(mid, 2)                        # exit back at the mean (20-MA)
        if disaster < entry < target:
            return TradeSignal("BUY", symbol, entry, disaster, target, "bb_mean_reversion")
    return _hold(symbol, "no_setup")


# ── E-003 · Donchian 200-day breakout + ATR trailing stop (daily, long+short) ─

def donchian_trend_tsl(symbol: str, df: pd.DataFrame, cfg: dict):
    """Go long on a new N-day high close, short on a new N-day low close; ride via
    an ATR trailing stop (the bot's trailing-SL manages the exit)."""
    from src.strategy import TradeSignal, _atr, _hold
    n = cfg.get("donchian_lookback", 200)
    atr_mult = cfg.get("donchian_atr_mult", 6.0)
    ride = cfg.get("donchian_ride_atr", 20)

    if len(df) < n + 2:
        return _hold(symbol, "insufficient_data")
    close = df["close"]
    last = float(close.iloc[-1])
    highest = float(close.iloc[-n:].max())
    lowest = float(close.iloc[-n:].min())
    atr = _atr(df, cfg.get("atr_period", 14))
    if atr <= 0:
        return _hold(symbol, "no_atr")

    if last >= highest:                               # new N-day high close
        stop = round(last - atr_mult * atr, 2)
        target = round(last + ride * atr, 2)          # far — TSL is the real exit
        return TradeSignal("BUY", symbol, last, stop, target, "donchian_breakout_long")
    if last <= lowest:                                # new N-day low close
        stop = round(last + atr_mult * atr, 2)
        target = round(last - ride * atr, 2)
        return TradeSignal("SELL", symbol, last, stop, target, "donchian_breakout_short")
    return _hold(symbol, "no_breakout")


# ── E-001 · Supertrend flip (intraday) ────────────────────────────────────────

def supertrend(symbol: str, df: pd.DataFrame, cfg: dict):
    """Enter on a Supertrend direction flip; SL/target from _sl_target (pct or ATR)."""
    from src.strategy import TradeSignal, _hold, _sl_target, _supertrend_dir
    period = cfg.get("supertrend_period", 10)
    mult = cfg.get("supertrend_mult", 3.0)
    direction = _supertrend_dir(df, period, mult)
    if direction is None or len(direction) < 2:
        return _hold(symbol, "insufficient_data")
    last = float(df["close"].iloc[-1])

    if direction[-1] == 1 and direction[-2] == -1:
        sl, tgt = _sl_target(df, last, "BUY", cfg)
        return TradeSignal("BUY", symbol, last, sl, tgt, "supertrend_flip_up")
    if direction[-1] == -1 and direction[-2] == 1:
        sl, tgt = _sl_target(df, last, "SELL", cfg)
        return TradeSignal("SELL", symbol, last, sl, tgt, "supertrend_flip_down")
    return _hold(symbol, "no_flip")


# ── E-008 · Opening Range Breakout — Nifty/stocks (intraday, NSE) ─────────────

def orb_nifty(symbol: str, df: pd.DataFrame, cfg: dict):
    """Break of the opening range (09:15→or_end) high/low, volume-confirmed, with a
    CAPPED stop so a wide OR doesn't oversize risk. (Two-trades/day is enforced by
    the RiskManager, not the signal.)"""
    from src.strategy import TradeSignal, _hold
    if "timestamp" not in df.columns:
        return _hold(symbol, "no_timestamp")
    or_end = cfg.get("orb_or_end", "09:30")
    max_stop_cap = cfg.get("orb_max_stop_cap_pts", 30)
    r_mult = cfg.get("orb_r_multiple", 2.0)
    oh, om = map(int, or_end.split(":"))

    d = df.copy()
    d["timestamp"] = pd.to_datetime(d["timestamp"])
    today = d["timestamp"].iloc[-1].date()
    day = d[d["timestamp"].dt.date == today]
    if len(day) < 2:
        return _hold(symbol, "insufficient_session")

    or_bars = day[day["timestamp"].dt.time < dtime(oh, om)]
    if len(or_bars) == 0:
        return _hold(symbol, "no_opening_range")
    if d["timestamp"].iloc[-1].time() < dtime(oh, om):
        return _hold(symbol, "opening_range_forming")

    or_high = float(or_bars["high"].max())
    or_low = float(or_bars["low"].min())
    last = float(day["close"].iloc[-1])

    vol_ok = True
    if cfg.get("orb_volume_confirm", True):
        vsma = day["volume"].rolling(cfg.get("volume_sma_period", 20)).mean().iloc[-1]
        vol_ok = bool(day["volume"].iloc[-1] > (vsma if vsma == vsma else 0))

    if last > or_high and vol_ok:
        dist = min(last - or_low, max_stop_cap)
        return TradeSignal("BUY", symbol, last, round(last - dist, 2),
                           round(last + r_mult * dist, 2), "orb_break_high")
    if last < or_low and vol_ok:
        dist = min(or_high - last, max_stop_cap)
        return TradeSignal("SELL", symbol, last, round(last + dist, 2),
                           round(last - r_mult * dist, 2), "orb_break_low")
    return _hold(symbol, "no_break")


REGISTRY = {
    "bb_mean_reversion": bb_mean_reversion,
    "donchian_trend_tsl": donchian_trend_tsl,
    "supertrend": supertrend,
    "orb_nifty": orb_nifty,
}
