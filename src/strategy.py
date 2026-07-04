"""
Strategy engine — Momentum / VWAP Breakout.
Computes indicators (VWAP, EMA 9/21, RSI 14, Volume SMA) and generates BUY/SELL/HOLD signals.
"""
from dataclasses import dataclass
from typing import Literal, Optional

import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator
from ta.volume import VolumeWeightedAveragePrice

from src.logger import get_logger

logger = get_logger("strategy")

Signal = Literal["BUY", "SELL", "HOLD"]


@dataclass
class TradeSignal:
    direction: Signal
    symbol: str
    entry_price: float
    stop_loss: float
    target: float
    reason: str


def _compute_indicators(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Append VWAP, EMA fast/slow, RSI, and Volume SMA columns in-place."""
    vwap = VolumeWeightedAveragePrice(
        high=df["high"], low=df["low"], close=df["close"], volume=df["volume"]
    )
    df = df.copy()
    df["vwap"] = vwap.volume_weighted_average_price()
    df["ema_fast"] = EMAIndicator(df["close"], window=cfg["ema_fast"]).ema_indicator()
    df["ema_slow"] = EMAIndicator(df["close"], window=cfg["ema_slow"]).ema_indicator()
    df["rsi"] = RSIIndicator(df["close"], window=cfg["rsi_period"]).rsi()
    df["vol_sma"] = df["volume"].rolling(cfg["volume_sma_period"]).mean()
    return df


def _ema_crossed_above(df: pd.DataFrame, lookback: int) -> bool:
    """True if ema_fast crossed above ema_slow within the last `lookback` candles."""
    recent = df.tail(lookback + 1).reset_index(drop=True)
    for i in range(1, len(recent)):
        if recent.at[i - 1, "ema_fast"] < recent.at[i - 1, "ema_slow"] and \
           recent.at[i, "ema_fast"] >= recent.at[i, "ema_slow"]:
            return True
    return False


def _ema_crossed_below(df: pd.DataFrame, lookback: int) -> bool:
    """True if ema_fast crossed below ema_slow within the last `lookback` candles."""
    recent = df.tail(lookback + 1).reset_index(drop=True)
    for i in range(1, len(recent)):
        if recent.at[i - 1, "ema_fast"] > recent.at[i - 1, "ema_slow"] and \
           recent.at[i, "ema_fast"] <= recent.at[i, "ema_slow"]:
            return True
    return False


def _min_rows(cfg: dict) -> int:
    return max(cfg["ema_slow"], cfg["rsi_period"], cfg["volume_sma_period"]) + 5


def _atr(df: pd.DataFrame, period: int = 14) -> float:
    """Average True Range of the last `period` candles (0.0 if not enough data)."""
    if len(df) < period + 1:
        return 0.0
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return float(tr.rolling(period).mean().iloc[-1])


def _sl_target(df: pd.DataFrame, entry: float, direction: str, cfg: dict) -> tuple[float, float]:
    """
    Stop-loss and target for an entry. Two modes (SCRUM-81):
    - sl_mode == 'atr': SL = atr_sl_mult × ATR, target = atr_target_mult × ATR
    - otherwise       : fixed stop_loss_pct / target_pct of entry price
    Falls back to fixed if ATR can't be computed.
    """
    if cfg.get("sl_mode") == "atr":
        atr = _atr(df, cfg.get("atr_period", 14))
        if atr > 0:
            sl_dist = cfg.get("atr_sl_mult", 1.5) * atr
            tgt_dist = cfg.get("atr_target_mult", 3.0) * atr
        else:
            sl_dist = entry * cfg.get("stop_loss_pct", 1.0) / 100
            tgt_dist = entry * cfg.get("target_pct", 2.0) / 100
    else:
        sl_dist = entry * cfg.get("stop_loss_pct", 1.0) / 100
        tgt_dist = entry * cfg.get("target_pct", 2.0) / 100

    if direction == "BUY":
        return round(entry - sl_dist, 2), round(entry + tgt_dist, 2)
    return round(entry + sl_dist, 2), round(entry - tgt_dist, 2)


# ── Strategy #1: Momentum / VWAP breakout ─────────────────────────────────────

def _momentum_vwap_breakout(symbol: str, df: pd.DataFrame, cfg: dict) -> TradeSignal:
    """
    Evaluate BUY/SELL/HOLD on the latest closed candle.
    df must have columns: open, high, low, close, volume (oldest first).
    """
    if len(df) < _min_rows(cfg):
        logger.warning(f"{symbol}: insufficient data ({len(df)} rows, need {_min_rows(cfg)})")
        return TradeSignal("HOLD", symbol, 0.0, 0.0, 0.0, "insufficient_data")

    ind = _compute_indicators(df, cfg)
    last = ind.iloc[-1]
    lookback = cfg["ema_crossover_lookback"]

    buy = (
        last["close"] > last["vwap"]
        and _ema_crossed_above(ind, lookback)
        and last["rsi"] > cfg["rsi_entry_threshold"]
        and last["volume"] >= last["vol_sma"] * cfg["volume_multiplier"]
    )
    if buy:
        sl, tgt = _sl_target(df, last["close"], "BUY", cfg)
        logger.info(f"{symbol}: BUY | close={last['close']} vwap={last['vwap']:.2f} rsi={last['rsi']:.1f}")
        return TradeSignal("BUY", symbol, last["close"], sl, tgt, "vwap_ema_rsi_volume")

    sell = (
        last["close"] < last["vwap"]
        and _ema_crossed_below(ind, lookback)
        and last["rsi"] < (100 - cfg["rsi_entry_threshold"])
        and last["volume"] >= last["vol_sma"] * cfg["volume_multiplier"]
    )
    if sell:
        sl, tgt = _sl_target(df, last["close"], "SELL", cfg)
        logger.info(f"{symbol}: SELL | close={last['close']} vwap={last['vwap']:.2f} rsi={last['rsi']:.1f}")
        return TradeSignal("SELL", symbol, last["close"], sl, tgt, "vwap_ema_rsi_volume_inverse")

    logger.info(f"{symbol}: HOLD — no signal")
    return TradeSignal("HOLD", symbol, 0.0, 0.0, 0.0, "no_conditions_met")


# ── Strategy #3: VWAP mean reversion ──────────────────────────────────────────

def _vwap_mean_reversion(symbol: str, df: pd.DataFrame, cfg: dict) -> TradeSignal:
    """
    Fade moves stretched away from VWAP back toward it (best in range-bound
    NEUTRAL regime — the counterpart to breakout).
    BUY when price is stretched far BELOW VWAP and RSI oversold; SELL when far
    ABOVE and RSI overbought.
    """
    if len(df) < _min_rows(cfg):
        return TradeSignal("HOLD", symbol, 0.0, 0.0, 0.0, "insufficient_data")

    ind = _compute_indicators(df, cfg)
    last = ind.iloc[-1]
    stretch = cfg.get("vwap_stretch_pct", 1.5) / 100
    rsi_ob = cfg.get("rsi_overbought", 70)
    rsi_os = cfg.get("rsi_oversold", 30)
    dist = (last["close"] - last["vwap"]) / last["vwap"] if last["vwap"] else 0.0

    if dist <= -stretch and last["rsi"] < rsi_os:
        sl, tgt = _sl_target(df, last["close"], "BUY", cfg)
        return TradeSignal("BUY", symbol, last["close"], sl, tgt, "vwap_reversion_long")
    if dist >= stretch and last["rsi"] > rsi_ob:
        sl, tgt = _sl_target(df, last["close"], "SELL", cfg)
        return TradeSignal("SELL", symbol, last["close"], sl, tgt, "vwap_reversion_short")

    return TradeSignal("HOLD", symbol, 0.0, 0.0, 0.0, "no_conditions_met")


# ── Strategy #2: Opening Range Breakout ───────────────────────────────────────

def _orb(symbol: str, df: pd.DataFrame, cfg: dict) -> TradeSignal:
    """
    Break of the opening-range (session start → orb_end) high/low with volume.
    Requires a 'timestamp' column; HOLDs if the opening range can't be resolved.
    """
    if "timestamp" not in df.columns or len(df) < 3:
        return TradeSignal("HOLD", symbol, 0.0, 0.0, 0.0, "no_timestamp")

    ts = pd.to_datetime(df["timestamp"])
    day = ts.iloc[-1].date()
    open_h, open_m = map(int, cfg.get("orb_start", "09:15").split(":"))
    end_h, end_m = map(int, cfg.get("orb_end", "09:45").split(":"))
    same_day = ts.dt.date == day
    in_or = same_day & (
        (ts.dt.hour * 60 + ts.dt.minute) >= open_h * 60 + open_m) & (
        (ts.dt.hour * 60 + ts.dt.minute) < end_h * 60 + end_m)
    or_rows = df[in_or.values]
    if or_rows.empty:
        return TradeSignal("HOLD", symbol, 0.0, 0.0, 0.0, "no_opening_range")

    or_high = or_rows["high"].max()
    or_low = or_rows["low"].min()
    last = df.iloc[-1]
    # only breakouts that occur after the opening range
    after_or = df[same_day.values & ~in_or.values]
    if after_or.empty:
        return TradeSignal("HOLD", symbol, 0.0, 0.0, 0.0, "within_opening_range")

    vol_ok = True
    if "volume" in df.columns and len(df) >= cfg.get("volume_sma_period", 20):
        vol_sma = df["volume"].rolling(cfg["volume_sma_period"]).mean().iloc[-1]
        vol_ok = last["volume"] >= vol_sma * cfg.get("volume_multiplier", 1.5)

    if last["close"] > or_high and vol_ok:
        sl, tgt = _sl_target(df, last["close"], "BUY", cfg)
        return TradeSignal("BUY", symbol, last["close"], sl, tgt, "orb_break_high")
    if last["close"] < or_low and vol_ok:
        sl, tgt = _sl_target(df, last["close"], "SELL", cfg)
        return TradeSignal("SELL", symbol, last["close"], sl, tgt, "orb_break_low")

    return TradeSignal("HOLD", symbol, 0.0, 0.0, 0.0, "no_break")


# ── Strategy #8: Supertrend (ATR trend-following) ─────────────────────────────

def _supertrend_dir(df: pd.DataFrame, period: int, mult: float) -> Optional[list]:
    """Return the per-candle supertrend direction (+1 up, -1 down), or None."""
    if len(df) < period + 1:
        return None
    close = df["close"].values
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(period).mean().values
    hl2 = (df["high"].values + df["low"].values) / 2

    direction = [1] * len(df)
    final_upper = [0.0] * len(df)
    final_lower = [0.0] * len(df)
    for i in range(len(df)):
        if atr[i] != atr[i] or i < period:  # NaN or warmup
            continue
        basic_upper = hl2[i] + mult * atr[i]
        basic_lower = hl2[i] - mult * atr[i]
        final_upper[i] = (basic_upper if (basic_upper < final_upper[i - 1] or close[i - 1] > final_upper[i - 1])
                          else final_upper[i - 1])
        final_lower[i] = (basic_lower if (basic_lower > final_lower[i - 1] or close[i - 1] < final_lower[i - 1])
                          else final_lower[i - 1])
        if close[i] > final_upper[i - 1]:
            direction[i] = 1
        elif close[i] < final_lower[i - 1]:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1]
    return direction


def _supertrend(symbol: str, df: pd.DataFrame, cfg: dict) -> TradeSignal:
    """Enter on a Supertrend flip (volatility-adaptive trend following)."""
    period = cfg.get("supertrend_period", 10)
    mult = cfg.get("supertrend_mult", 3.0)
    direction = _supertrend_dir(df, period, mult)
    if direction is None or len(direction) < 2:
        return TradeSignal("HOLD", symbol, 0.0, 0.0, 0.0, "insufficient_data")

    last_close = float(df["close"].iloc[-1])
    if direction[-1] == 1 and direction[-2] == -1:
        sl, tgt = _sl_target(df, last_close, "BUY", cfg)
        return TradeSignal("BUY", symbol, last_close, sl, tgt, "supertrend_flip_up")
    if direction[-1] == -1 and direction[-2] == 1:
        sl, tgt = _sl_target(df, last_close, "SELL", cfg)
        return TradeSignal("SELL", symbol, last_close, sl, tgt, "supertrend_flip_down")

    return TradeSignal("HOLD", symbol, 0.0, 0.0, 0.0, "no_flip")


# ── Registry & dispatcher ─────────────────────────────────────────────────────

STRATEGY_REGISTRY = {
    "momentum_vwap_breakout": _momentum_vwap_breakout,
    "vwap_mean_reversion":    _vwap_mean_reversion,
    "orb":                    _orb,
    "supertrend":             _supertrend,
}


def generate_signal(symbol: str, df: pd.DataFrame, cfg: dict) -> TradeSignal:
    """
    Dispatch to the active strategy named by cfg['name'] (default: momentum).
    Keeps the historical signature so main.py and the backtester call it unchanged.
    """
    name = cfg.get("name", "momentum_vwap_breakout")
    strategy_fn = STRATEGY_REGISTRY.get(name)
    if strategy_fn is None:
        logger.error(f"Unknown strategy '{name}' — falling back to momentum")
        strategy_fn = _momentum_vwap_breakout
    return strategy_fn(symbol, df, cfg)


Regime = Literal["BULLISH", "BEARISH", "NEUTRAL"]


def market_regime(df: pd.DataFrame, cfg: dict) -> Regime:
    """
    Classify the index trend so entries align with the broader market (SCRUM-67).
    BULLISH: index close above EMA by more than the neutral band.
    BEARISH: below by more than the band.
    NEUTRAL: inside the band (choppy) — no entries should be taken.
    df: index candles [.., close, ..]; cfg: strategy section.
    """
    window = cfg.get("regime_ema", 20)
    band = cfg.get("regime_band_pct", 0.1) / 100

    if df is None or len(df) < window + 5:
        logger.warning(f"market_regime: insufficient index data ({0 if df is None else len(df)} rows)")
        return "NEUTRAL"

    ema = EMAIndicator(df["close"], window=window).ema_indicator()
    last_close = df["close"].iloc[-1]
    last_ema = ema.iloc[-1]

    if last_close > last_ema * (1 + band):
        return "BULLISH"
    if last_close < last_ema * (1 - band):
        return "BEARISH"
    return "NEUTRAL"
