"""
Timeframe resampling (SCRUM-108 / B1) — pure, no I/O, no now().

Aggregates a lower-timeframe OHLCV frame into a higher timeframe for the
multi-timeframe confirmation gate. Two correctness properties are the whole
point of this module:

1. **Session-aligned origin.** NSE trades 09:15–15:30. Kite's native 60-minute
   candles align to 09:15 (09:15–10:15, …), NOT to clock hours. We bin with
   origin at 09:15 so a resampled 1-hr bar matches Kite's native bar exactly —
   otherwise backtest and live would gate on differently-phased trends.

2. **Closed-bar rule.** A higher-TF bar is emitted only if its close time is at
   or before `now` (the forming bar is always dropped). This single predicate
   is the look-ahead guarantee.
"""
from datetime import datetime
from typing import Optional

import pandas as pd

_TF_MINUTES = {"1min": 1, "5min": 5, "15min": 15, "30min": 30, "1hr": 60}
_SESSION_OPEN = "09:15"


def tf_minutes(tf: str) -> int:
    if tf not in _TF_MINUTES:
        raise ValueError(f"unknown timeframe '{tf}' (known: {list(_TF_MINUTES)})")
    return _TF_MINUTES[tf]


def resample_ohlcv(df: pd.DataFrame, target_tf: str,
                   now: Optional[datetime] = None) -> pd.DataFrame:
    """
    df: OHLCV with a 'timestamp' column (tz-aware or naive), oldest first.
    Returns higher-TF OHLCV, session-aligned (origin 09:15), CLOSED bars only.
    If `now` is None, all fully-formed bars in the data are returned.
    """
    minutes = tf_minutes(target_tf)
    if df is None or df.empty:
        return df if df is not None else pd.DataFrame(
            columns=["timestamp", "open", "high", "low", "close", "volume"])

    d = df.copy()
    d["timestamp"] = pd.to_datetime(d["timestamp"])
    tz = d["timestamp"].dt.tz
    d = d.set_index("timestamp").sort_index()

    # origin at the session open of the first day, so bins start at 09:15
    first_day = d.index[0].normalize()
    origin = first_day + pd.Timedelta(_SESSION_OPEN + ":00")
    if tz is not None and origin.tzinfo is None:
        origin = origin.tz_localize(tz)

    agg = d.resample(f"{minutes}min", origin=origin, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    agg = agg.dropna(subset=["open"])                    # drop empty (overnight) bins

    if now is not None:
        now_ts = pd.Timestamp(now)
        if tz is not None and now_ts.tzinfo is None:
            now_ts = now_ts.tz_localize(tz)
        # keep a bar only if it has fully closed: bar_start + interval <= now
        bar_close = agg.index + pd.Timedelta(minutes=minutes)
        agg = agg[bar_close <= now_ts]

    return agg.reset_index()
