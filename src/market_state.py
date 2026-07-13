"""
MarketState layer (dependency for the regime router) — a pure snapshot of the
market computed from CLOSED bars only.

`compute_market_state(df, cfg, breadth)` turns an OHLCV frame into a frozen vector
of trend / strength / volatility / compression features. No I/O, no Kite, no
now() — it reads only the rows it is given, so it is identical in backtest, paper
and live and cannot look ahead (the caller passes bars closed as of `now`).
"""
from dataclasses import dataclass
from typing import Optional

import pandas as pd
from ta.trend import ADXIndicator, EMAIndicator
from ta.volatility import AverageTrueRange, BollingerBands


@dataclass(frozen=True)
class MarketState:
    close: float
    ema_fast: float
    ema_slow: float
    ema_slope: float          # fractional slope of the slow EMA over slope_lookback bars
    adx: float                # trend strength
    atr: float
    atr_pct: float            # ATR as % of price
    bb_width: float           # (upper-lower)/mid
    bb_width_pctile: float    # 0..1 percentile of current width vs recent history
    breadth: Optional[float]  # % of universe above VWAP (None if not supplied)
    n_bars: int
    config_version: str = ""


_DEFAULTS = {
    "ms_ema_fast": 20, "ms_ema_slow": 50, "ms_slope_lookback": 5,
    "ms_adx_period": 14, "ms_atr_period": 14,
    "ms_bb_period": 20, "ms_bb_dev": 2.0, "ms_bb_width_window": 100,
}


def _cfg(cfg: dict, key: str):
    return (cfg or {}).get(key, _DEFAULTS[key])


def min_bars_needed(cfg: dict) -> int:
    return max(_cfg(cfg, "ms_ema_slow"), _cfg(cfg, "ms_adx_period") * 2,
              _cfg(cfg, "ms_bb_period"), _cfg(cfg, "ms_slope_lookback") + 1) + 5


def _last(series: pd.Series, default: float = 0.0) -> float:
    if series is None or len(series) == 0:
        return default
    v = series.iloc[-1]
    return float(v) if v == v else default   # NaN -> default


def compute_market_state(df: pd.DataFrame, cfg: Optional[dict] = None,
                         breadth: Optional[float] = None,
                         config_version: str = "") -> MarketState:
    """
    Build a MarketState from the CLOSED bars in `df` (last row = current bar).
    Returns a state with n_bars = len(df); the classifier treats a state with too
    few bars as UNKNOWN, so callers don't need to guard length here.
    """
    cfg = cfg or {}
    n = 0 if df is None else len(df)
    if n == 0:
        return MarketState(0, 0, 0, 0, 0, 0, 0, 0, 0.0, breadth, 0, config_version)

    close = float(df["close"].iloc[-1])
    ema_fast = _last(EMAIndicator(df["close"], window=_cfg(cfg, "ms_ema_fast")).ema_indicator(), close)
    slow_win = _cfg(cfg, "ms_ema_slow")
    ema_slow_series = EMAIndicator(df["close"], window=slow_win).ema_indicator()
    ema_slow = _last(ema_slow_series, close)

    slope_lb = _cfg(cfg, "ms_slope_lookback")
    if len(ema_slow_series.dropna()) > slope_lb:
        prev = ema_slow_series.iloc[-1 - slope_lb]
        ema_slope = float((ema_slow - prev) / prev) if prev else 0.0
    else:
        ema_slope = 0.0

    adx = _last(ADXIndicator(df["high"], df["low"], df["close"],
                             window=_cfg(cfg, "ms_adx_period")).adx(), 0.0)
    atr = _last(AverageTrueRange(df["high"], df["low"], df["close"],
                                 window=_cfg(cfg, "ms_atr_period")).average_true_range(), 0.0)
    atr_pct = (atr / close * 100.0) if close else 0.0

    bb = BollingerBands(df["close"], window=_cfg(cfg, "ms_bb_period"),
                        window_dev=_cfg(cfg, "ms_bb_dev"))
    mid = bb.bollinger_mavg()
    width_series = (bb.bollinger_hband() - bb.bollinger_lband()) / mid.replace(0, pd.NA)
    bb_width = _last(width_series, 0.0)
    recent = width_series.dropna().tail(_cfg(cfg, "ms_bb_width_window"))
    if len(recent) >= 2:
        bb_width_pctile = float((recent < bb_width).sum() / len(recent))
    else:
        bb_width_pctile = 0.0

    return MarketState(
        close=close, ema_fast=ema_fast, ema_slow=ema_slow, ema_slope=ema_slope,
        adx=adx, atr=atr, atr_pct=atr_pct, bb_width=bb_width,
        bb_width_pctile=bb_width_pctile, breadth=breadth, n_bars=n,
        config_version=config_version)
