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


def _session_vwap(df: pd.DataFrame) -> pd.Series:
    """Session-anchored VWAP (resets each trading day). Needs timestamp + volume."""
    d = df.copy()
    d["timestamp"] = pd.to_datetime(d["timestamp"])
    tp = (d["high"] + d["low"] + d["close"]) / 3
    day = d["timestamp"].dt.date
    cum_pv = (tp * d["volume"]).groupby(day).cumsum()
    cum_v = d["volume"].groupby(day).cumsum()
    return cum_pv / cum_v.replace(0, 1e-9)


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


# ═══════════════════════════════════════════════════════════════════════════════
# BATCH 1 — pure-OHLCV strategies from the mined catalog (S-16/19/21/23/34).
# All UNVALIDATED sweep starts. Each enters at the signal-bar close (a market
# entry), so the backtester's realistic limit-fill guard does not apply. Testable
# on BOTH intraday (15min) and daily bars.
# ═══════════════════════════════════════════════════════════════════════════════

def inside_bar_breakout(symbol: str, df: pd.DataFrame, cfg: dict):
    """S-23 · Mother bar fully contains the next (inside) bar → coiled; trade the
    break of the mother bar's high (long) / low (short). Stop = opposite extreme."""
    from src.strategy import TradeSignal, _hold
    r_mult = cfg.get("ib_r_multiple", 2.0)
    if len(df) < 3:
        return _hold(symbol, "insufficient_data")
    mother, inside, cur = df.iloc[-3], df.iloc[-2], df.iloc[-1]
    if not (inside["high"] <= mother["high"] and inside["low"] >= mother["low"]):
        return _hold(symbol, "no_inside_bar")
    mh, ml, last = float(mother["high"]), float(mother["low"]), float(cur["close"])
    if last > mh:
        dist = last - ml
        return TradeSignal("BUY", symbol, last, round(ml, 2),
                           round(last + r_mult * dist, 2), "inside_bar_break_up")
    if last < ml:
        dist = mh - last
        return TradeSignal("SELL", symbol, last, round(mh, 2),
                           round(last - r_mult * dist, 2), "inside_bar_break_down")
    return _hold(symbol, "no_break")


def volatility_contraction_breakout(symbol: str, df: pd.DataFrame, cfg: dict):
    """S-21 · Coil then expand: Bollinger-band width in its narrowest percentile
    over the lookback, then price breaks the recent range. Stop = opposite boundary."""
    from src.strategy import TradeSignal, _hold
    bb_p = cfg.get("vcb_bb_period", 20)
    lookback = cfg.get("vcb_lookback", 100)
    pctile = cfg.get("vcb_width_pctile", 20)
    range_n = cfg.get("vcb_range_bars", 10)
    r_mult = cfg.get("vcb_r_multiple", 2.0)
    if len(df) < max(bb_p, lookback) + 2:
        return _hold(symbol, "insufficient_data")
    close = df["close"]
    mid = close.rolling(bb_p).mean()
    width = close.rolling(bb_p).std() / mid           # normalized band width
    cur_w = float(width.iloc[-1])
    thresh = float(width.iloc[-lookback:].quantile(pctile / 100.0))
    if cur_w != cur_w or cur_w > thresh:              # NaN or not contracted
        return _hold(symbol, "not_contracted")
    hi = float(df["high"].iloc[-range_n - 1:-1].max())   # range excludes current bar
    lo = float(df["low"].iloc[-range_n - 1:-1].min())
    last = float(close.iloc[-1])
    if last > hi:
        dist = last - lo
        return TradeSignal("BUY", symbol, last, round(lo, 2),
                           round(last + r_mult * dist, 2), "vcb_break_up")
    if last < lo:
        dist = hi - last
        return TradeSignal("SELL", symbol, last, round(hi, 2),
                           round(last - r_mult * dist, 2), "vcb_break_down")
    return _hold(symbol, "no_break")


def fair_value_gap(symbol: str, df: pd.DataFrame, cfg: dict):
    """S-34 · Three-candle imbalance (candle -3 and -1 ranges don't overlap → the
    middle candle left an unfilled gap); trade continuation in the gap direction."""
    from src.strategy import TradeSignal, _hold
    r_mult = cfg.get("fvg_r_multiple", 2.0)
    if len(df) < 3:
        return _hold(symbol, "insufficient_data")
    c3, c1 = df.iloc[-3], df.iloc[-1]
    last = float(c1["close"])
    if float(c3["high"]) < float(c1["low"]):          # bullish imbalance (gap up)
        gap_lo = float(c3["high"])
        dist = last - gap_lo
        if dist > 0:
            return TradeSignal("BUY", symbol, last, round(gap_lo, 2),
                               round(last + r_mult * dist, 2), "fvg_bull")
    if float(c3["low"]) > float(c1["high"]):          # bearish imbalance (gap down)
        gap_hi = float(c3["low"])
        dist = gap_hi - last
        if dist > 0:
            return TradeSignal("SELL", symbol, last, round(gap_hi, 2),
                               round(last - r_mult * dist, 2), "fvg_bear")
    return _hold(symbol, "no_fvg")


def double_reversal(symbol: str, df: pd.DataFrame, cfg: dict):
    """S-19 · Double bottom (long) / double top (short): two comparable extremes
    (within tol%) separated by a swing, entered on the neckline break."""
    from src.strategy import TradeSignal, _hold
    tol = cfg.get("db_tol_pct", 1.0)
    win = cfg.get("db_lookback", 40)
    min_sep = cfg.get("db_min_sep", 5)
    r_mult = cfg.get("db_r_multiple", 2.0)
    if len(df) < win + 2:
        return _hold(symbol, "insufficient_data")
    seg = df.iloc[-win:]
    half = win // 2
    last = float(df["close"].iloc[-1])

    # double bottom → long
    lo1 = float(seg["low"].iloc[:half].min())
    lo2 = float(seg["low"].iloc[half:].min())
    i1 = int(seg["low"].iloc[:half].values.argmin())
    i2 = half + int(seg["low"].iloc[half:].values.argmin())
    if abs(lo1 - lo2) / max(lo1, 1e-9) * 100 <= tol and (i2 - i1) >= min_sep:
        neck = float(seg["high"].iloc[i1:i2 + 1].max())
        if last > neck:
            stop = min(lo1, lo2)
            return TradeSignal("BUY", symbol, last, round(stop, 2),
                               round(last + r_mult * (last - stop), 2), "double_bottom")

    # double top → short
    hi1 = float(seg["high"].iloc[:half].max())
    hi2 = float(seg["high"].iloc[half:].max())
    j1 = int(seg["high"].iloc[:half].values.argmax())
    j2 = half + int(seg["high"].iloc[half:].values.argmax())
    if abs(hi1 - hi2) / max(hi1, 1e-9) * 100 <= tol and (j2 - j1) >= min_sep:
        neck = float(seg["low"].iloc[j1:j2 + 1].min())
        if last < neck:
            stop = max(hi1, hi2)
            return TradeSignal("SELL", symbol, last, round(stop, 2),
                               round(last - r_mult * (stop - last), 2), "double_top")
    return _hold(symbol, "no_pattern")


def rsi_reversion(symbol: str, df: pd.DataFrame, cfg: dict):
    """S-16 · RSI mean-reversion: buy the cross UP out of oversold, short the cross
    DOWN out of overbought. SL/target from _sl_target (fixed pct or ATR)."""
    from src.strategy import TradeSignal, _hold, _sl_target
    period = cfg.get("rsi_period", 14)
    os_lvl = cfg.get("rsi_oversold", 30)
    ob_lvl = cfg.get("rsi_overbought", 70)
    if len(df) < period + 3:
        return _hold(symbol, "insufficient_data")
    delta = df["close"].diff()
    up = delta.clip(lower=0).rolling(period).mean()
    down = (-delta.clip(upper=0)).rolling(period).mean()
    rsi = 100 - 100 / (1 + up / down.replace(0, 1e-9))
    r_now, r_prev = float(rsi.iloc[-1]), float(rsi.iloc[-2])
    last = float(df["close"].iloc[-1])
    if r_prev < os_lvl <= r_now:
        sl, tgt = _sl_target(df, last, "BUY", cfg)
        return TradeSignal("BUY", symbol, last, sl, tgt, "rsi_reversion_long")
    if r_prev > ob_lvl >= r_now:
        sl, tgt = _sl_target(df, last, "SELL", cfg)
        return TradeSignal("SELL", symbol, last, sl, tgt, "rsi_reversion_short")
    return _hold(symbol, "no_rsi_signal")


# ═══════════════════════════════════════════════════════════════════════════════
# BATCH 2 — pure-OHLCV catalog strategies (S-08/14/15/18/20/32/33). Unvalidated
# sweep starts; testable on both intraday and daily.
# ═══════════════════════════════════════════════════════════════════════════════

def abcd_pattern(symbol: str, df: pd.DataFrame, cfg: dict):
    """S-08 · A=swing low, B=swing high, C=higher pullback low (>A); the break of B
    is D → long. Uses confirmed swing pivots. Stop below C."""
    from src.strategy import TradeSignal, _hold, _swing_pivots
    win = cfg.get("abcd_lookback", 60)
    k = cfg.get("abcd_pivot_k", 3)
    r_mult = cfg.get("abcd_r_multiple", 2.0)
    if len(df) < win + k + 2:
        return _hold(symbol, "insufficient_data")
    seg = df.iloc[-win:].reset_index(drop=True)
    highs, lows = _swing_pivots(seg, k)
    if len(lows) < 2 or not highs:
        return _hold(symbol, "no_pivots")
    last = float(seg["close"].iloc[-1])
    for c_pos, c_lo in reversed(lows):                # most recent C first
        bs = [(p, v) for p, v in highs if p < c_pos]
        if not bs:
            continue
        b_pos, b_hi = max(bs, key=lambda t: t[1])     # B = highest swing high before C
        a_lows = [(p, v) for p, v in lows if p < b_pos]
        if not a_lows:
            continue
        a_lo = min(v for _, v in a_lows)              # A = lowest swing low before B
        if c_lo > a_lo and last > b_hi:               # higher low + break of B
            return TradeSignal("BUY", symbol, last, round(c_lo, 2),
                               round(last + r_mult * (last - c_lo), 2), "abcd_long")
    return _hold(symbol, "no_pattern")


def ma_pullback(symbol: str, df: pd.DataFrame, cfg: dict):
    """S-15 · Uptrend (close>SMA_ctx, EMA_slow>SMA_ctx); this bar dips to EMA_fast then
    closes back above it → long. Stop at the bar low."""
    from src.strategy import TradeSignal, _hold
    fast, slow, ctx = cfg.get("ma_fast", 9), cfg.get("ma_slow", 20), cfg.get("ma_ctx", 200)
    r_mult = cfg.get("ma_r_multiple", 2.0)
    if len(df) < ctx + 3:
        return _hold(symbol, "insufficient_data")
    close = df["close"]
    ef = float(close.ewm(span=fast).mean().iloc[-1])
    es = float(close.ewm(span=slow).mean().iloc[-1])
    sc = float(close.rolling(ctx).mean().iloc[-1])
    last, low_now = float(close.iloc[-1]), float(df["low"].iloc[-1])
    if last > sc and es > sc and low_now <= ef and last > ef and low_now < last:
        return TradeSignal("BUY", symbol, last, round(low_now, 2),
                           round(last + r_mult * (last - low_now), 2), "ma_pullback_long")
    return _hold(symbol, "no_setup")


def dip_buy_momentum(symbol: str, df: pd.DataFrame, cfg: dict):
    """S-14 · A sharp flush over the last N bars, then the first candle to make a new
    N-bar high → long. Stop at the flush low."""
    from src.strategy import TradeSignal, _hold
    flush_pct = cfg.get("flush_pct_min", 2.0)
    look = cfg.get("flush_lookback", 5)
    r_mult = cfg.get("dip_r_multiple", 2.0)
    if len(df) < look + 3:
        return _hold(symbol, "insufficient_data")
    flush_low = float(df["low"].iloc[-look - 1:].min())
    recent_high = float(df["high"].iloc[-look - 1:-1].max())
    last = float(df["close"].iloc[-1])
    ref = float(df["close"].iloc[-look - 1])
    if (flush_low - ref) / ref * 100 <= -flush_pct and last > recent_high and flush_low < last:
        return TradeSignal("BUY", symbol, last, round(flush_low, 2),
                           round(last + r_mult * (last - flush_low), 2), "dip_buy_momentum")
    return _hold(symbol, "no_setup")


def index_dip_reversion(symbol: str, df: pd.DataFrame, cfg: dict):
    """S-33 · Buy a >X% down day while above the long MA (dip within an uptrend);
    ATR stop, R target. Mean-reversion — pairs with S-25 rotation once sector data lands."""
    from src.strategy import TradeSignal, _hold, _atr
    dip_pct = cfg.get("idx_dip_pct_min", 1.5)
    ma = cfg.get("idx_ma", 200)
    r_mult = cfg.get("idx_r_multiple", 2.0)
    stop_atr = cfg.get("idx_atr_mult", 2.0)
    if len(df) < ma + 3:
        return _hold(symbol, "insufficient_data")
    close = df["close"]
    last, prev = float(close.iloc[-1]), float(close.iloc[-2])
    sma = float(close.rolling(ma).mean().iloc[-1])
    atr = _atr(df, 14)
    if last > sma and (last - prev) / prev * 100 <= -dip_pct and atr > 0:
        stop = round(last - stop_atr * atr, 2)
        if stop < last:
            return TradeSignal("BUY", symbol, last, stop,
                               round(last + r_mult * (last - stop), 2), "index_dip_reversion")
    return _hold(symbol, "no_dip")


def trendline_bounce(symbol: str, df: pd.DataFrame, cfg: dict):
    """S-18 · Fit a rising line to recent lows; long when the bar's low touches the
    line and the bar closes above it. Stop below the line."""
    from src.strategy import TradeSignal, _hold
    import numpy as np
    win = cfg.get("tl_lookback", 40)
    tol = cfg.get("tl_tol_pct", 0.5)
    r_mult = cfg.get("tl_r_multiple", 2.0)
    if len(df) < win + 3:
        return _hold(symbol, "insufficient_data")
    lows = df["low"].iloc[-win:].values
    x = np.arange(len(lows))
    slope, intercept = np.polyfit(x, lows, 1)
    if slope <= 0:
        return _hold(symbol, "not_rising")
    line_now = slope * (len(lows) - 1) + intercept
    last, low_now = float(df["close"].iloc[-1]), float(df["low"].iloc[-1])
    near = line_now * (1 - tol / 100) <= low_now <= line_now * (1 + tol / 100)
    if near and last > line_now:
        stop = round(line_now * (1 - 2 * tol / 100), 2)
        if stop < last:
            return TradeSignal("BUY", symbol, last, stop,
                               round(last + r_mult * (last - stop), 2), "trendline_bounce")
    return _hold(symbol, "no_bounce")


def head_shoulders(symbol: str, df: pd.DataFrame, cfg: dict):
    """S-20 · Head & shoulders (short) / inverse (long): the last three swing pivots
    with the middle the extreme and comparable shoulders, entered on the neckline
    break. Uses confirmed swing pivots."""
    from src.strategy import TradeSignal, _hold, _swing_pivots
    win = cfg.get("hs_lookback", 80)
    k = cfg.get("hs_pivot_k", 3)
    tol = cfg.get("hs_shoulder_tol_pct", 3.0)
    r_mult = cfg.get("hs_r_multiple", 2.0)
    if len(df) < win + k + 2:
        return _hold(symbol, "insufficient_data")
    seg = df.iloc[-win:].reset_index(drop=True)
    highs, lows = _swing_pivots(seg, k)
    last = float(seg["close"].iloc[-1])
    # H&S top → short: last 3 pivot highs, head highest, shoulders comparable
    if len(highs) >= 3 and len(lows) >= 2:
        ls, hd, rs = highs[-3], highs[-2], highs[-1]
        if hd[1] > ls[1] and hd[1] > rs[1] and abs(ls[1] - rs[1]) / max(ls[1], 1e-9) * 100 <= tol:
            necks = [v for p, v in lows if ls[0] < p < rs[0]]
            if necks and last < min(necks):
                return TradeSignal("SELL", symbol, last, round(rs[1], 2),
                                   round(last - r_mult * (rs[1] - last), 2), "head_shoulders")
    # inverse H&S → long: last 3 pivot lows, head lowest
    if len(lows) >= 3 and len(highs) >= 2:
        ls, hd, rs = lows[-3], lows[-2], lows[-1]
        if hd[1] < ls[1] and hd[1] < rs[1] and abs(ls[1] - rs[1]) / max(ls[1], 1e-9) * 100 <= tol:
            necks = [v for p, v in highs if ls[0] < p < rs[0]]
            if necks and last > max(necks):
                return TradeSignal("BUY", symbol, last, round(rs[1], 2),
                                   round(last + r_mult * (last - rs[1]), 2), "inverse_head_shoulders")
    return _hold(symbol, "no_pattern")


def engulfing_macd(symbol: str, df: pd.DataFrame, cfg: dict):
    """S-32 · Engulfing candle in the direction MACD agrees with. SL/target from
    _sl_target."""
    from src.strategy import TradeSignal, _hold, _sl_target
    if len(df) < 40:
        return _hold(symbol, "insufficient_data")
    o1, c1 = float(df["open"].iloc[-1]), float(df["close"].iloc[-1])
    o2, c2 = float(df["open"].iloc[-2]), float(df["close"].iloc[-2])
    close = df["close"]
    macd = close.ewm(span=12).mean() - close.ewm(span=26).mean()
    hist = float(macd.iloc[-1] - macd.ewm(span=9).mean().iloc[-1])
    if c1 > o1 and c2 < o2 and c1 >= o2 and o1 <= c2 and hist > 0:        # bullish engulf
        sl, tgt = _sl_target(df, c1, "BUY", cfg)
        return TradeSignal("BUY", symbol, c1, sl, tgt, "engulfing_bull_macd")
    if c1 < o1 and c2 > o2 and c1 <= o2 and o1 >= c2 and hist < 0:        # bearish engulf
        sl, tgt = _sl_target(df, c1, "SELL", cfg)
        return TradeSignal("SELL", symbol, c1, sl, tgt, "engulfing_bear_macd")
    return _hold(symbol, "no_setup")


# ═══════════════════════════════════════════════════════════════════════════════
# BATCH 3 — VWAP family (S-09/10/11), intraday-only (session-anchored VWAP needs
# timestamp + volume). Unvalidated sweep starts.
# ═══════════════════════════════════════════════════════════════════════════════

def red_to_green_vwap(symbol: str, df: pd.DataFrame, cfg: dict):
    """S-09 · Price reclaims session VWAP from below (prev bar under, current closes
    above) → long. Stop just below VWAP."""
    from src.strategy import TradeSignal, _hold
    r_mult = cfg.get("vwap_r_multiple", 2.0)
    if "timestamp" not in df.columns or len(df) < 20:
        return _hold(symbol, "no_timestamp")
    vwap = _session_vwap(df)
    last, prev = float(df["close"].iloc[-1]), float(df["close"].iloc[-2])
    v_now, v_prev = float(vwap.iloc[-1]), float(vwap.iloc[-2])
    if v_now != v_now:
        return _hold(symbol, "no_vwap")
    if prev < v_prev and last > v_now:
        stop = round(v_now * (1 - cfg.get("vwap_stop_pct", 0.3) / 100), 2)
        if stop < last:
            return TradeSignal("BUY", symbol, last, stop,
                               round(last + r_mult * (last - stop), 2), "r2g_vwap")
    return _hold(symbol, "no_reclaim")


def vwap_break_short(symbol: str, df: pd.DataFrame, cfg: dict):
    """S-10 · Held above VWAP then breaks and closes below → short. Stop just above VWAP."""
    from src.strategy import TradeSignal, _hold
    r_mult = cfg.get("vwap_r_multiple", 2.0)
    if "timestamp" not in df.columns or len(df) < 20:
        return _hold(symbol, "no_timestamp")
    vwap = _session_vwap(df)
    last, prev = float(df["close"].iloc[-1]), float(df["close"].iloc[-2])
    v_now, v_prev = float(vwap.iloc[-1]), float(vwap.iloc[-2])
    if v_now != v_now:
        return _hold(symbol, "no_vwap")
    if prev > v_prev and last < v_now:
        stop = round(v_now * (1 + cfg.get("vwap_stop_pct", 0.3) / 100), 2)
        if stop > last:
            return TradeSignal("SELL", symbol, last, stop,
                               round(last - r_mult * (stop - last), 2), "vwap_break_short")
    return _hold(symbol, "no_break")


def vwap_squeeze(symbol: str, df: pd.DataFrame, cfg: dict):
    """S-11 · Price coils tight near VWAP (small range, close to the line), then breaks
    the coil → trade the break. (Rules inferred — the source video had no captions.)"""
    from src.strategy import TradeSignal, _hold
    n = cfg.get("vwap_coil_bars", 5)
    max_range = cfg.get("vwap_coil_range_pct", 0.5)
    max_dist = cfg.get("vwap_coil_dist_pct", 0.3)
    r_mult = cfg.get("vwap_r_multiple", 2.0)
    if "timestamp" not in df.columns or len(df) < n + 5:
        return _hold(symbol, "no_timestamp")
    vwap = _session_vwap(df)
    v_now = float(vwap.iloc[-1])
    if v_now != v_now:
        return _hold(symbol, "no_vwap")
    coil = df.iloc[-n - 1:-1]
    hi, lo = float(coil["high"].max()), float(coil["low"].min())
    if (hi - lo) / v_now * 100 > max_range:
        return _hold(symbol, "not_coiled")
    if abs(float(coil["close"].mean()) - v_now) / v_now * 100 > max_dist:
        return _hold(symbol, "not_at_vwap")
    last = float(df["close"].iloc[-1])
    if last > hi:
        return TradeSignal("BUY", symbol, last, round(lo, 2),
                           round(last + r_mult * (last - lo), 2), "vwap_squeeze_up")
    if last < lo:
        return TradeSignal("SELL", symbol, last, round(hi, 2),
                           round(last - r_mult * (hi - last), 2), "vwap_squeeze_down")
    return _hold(symbol, "no_break")


# ── Maker reserve-CERTIFIED edge · family ebf605d5 ────────────────────────────
# The FIRST strategy to clear the Strategy Maker's full funnel INCLUDING the locked
# reserve holdout (cutoff 2026-01-17): objective prior-day-high context + a resume to a
# new 5-bar high, long only, ATR(14)x6 trailing exit. Reserve OOS: PF 2.80, 25 trades,
# +Rs.17,313 on data no search stage ever saw. We DELEGATE to the exact compiled maker
# candidate so the backtester/live runs the same pure fn that was certified — zero
# re-implementation drift. Params are certification-fixed (not sweep starts). Faithful
# reproduction needs delivery costs + backtest.trailing_mode 'atr', trailing_atr_mult 6.
_MAKER_EBF605D5 = None


def pdh_resume_breakout(symbol: str, df: pd.DataFrame, cfg: dict):
    global _MAKER_EBF605D5
    if _MAKER_EBF605D5 is None:
        from maker.grammar import compile as _compile, make_candidate
        _MAKER_EBF605D5 = _compile(make_candidate("long", {
            "setup": ("objective_level", {"level": "pdh"}),
            "trigger": ("resume_new_high", {"within_bars": 5}),
            "exit": ("atr_trail", {"mult": 6, "period": 14})}))
    sig = _MAKER_EBF605D5(symbol, df, cfg)
    if sig.direction == "HOLD":
        return sig
    from src.strategy import TradeSignal            # re-tag with the strategy name
    return TradeSignal(sig.direction, symbol, sig.entry_price, sig.stop_loss,
                       sig.target, "pdh_resume_breakout")


REGISTRY = {
    "bb_mean_reversion": bb_mean_reversion,
    "donchian_trend_tsl": donchian_trend_tsl,
    "supertrend": supertrend,
    "orb_nifty": orb_nifty,
    # Batch 1 (mined catalog)
    "inside_bar_breakout": inside_bar_breakout,
    "volatility_contraction_breakout": volatility_contraction_breakout,
    "fair_value_gap": fair_value_gap,
    "double_reversal": double_reversal,
    "rsi_reversion": rsi_reversion,
    # Batch 2 (mined catalog)
    "abcd_pattern": abcd_pattern,
    "ma_pullback": ma_pullback,
    "dip_buy_momentum": dip_buy_momentum,
    "index_dip_reversion": index_dip_reversion,
    "trendline_bounce": trendline_bounce,
    "head_shoulders": head_shoulders,
    "engulfing_macd": engulfing_macd,
    # Batch 3 (VWAP family, intraday)
    "red_to_green_vwap": red_to_green_vwap,
    "vwap_break_short": vwap_break_short,
    "vwap_squeeze": vwap_squeeze,
    # Maker reserve-CERTIFIED (family ebf605d5)
    "pdh_resume_breakout": pdh_resume_breakout,
}
