"""
Strategy engine — Momentum / VWAP Breakout.
Computes indicators (VWAP, EMA 9/21, RSI 14, Volume SMA) and generates BUY/SELL/HOLD signals.
"""
from dataclasses import dataclass
from typing import Literal

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


def generate_signal(symbol: str, df: pd.DataFrame, cfg: dict) -> TradeSignal:
    """
    Evaluate BUY/SELL/HOLD on the latest closed 5-min candle.
    df must have columns: open, high, low, close, volume (oldest first).
    cfg: strategy section from config.yaml.
    """
    if len(df) < _min_rows(cfg):
        logger.warning(f"{symbol}: insufficient data ({len(df)} rows, need {_min_rows(cfg)})")
        return TradeSignal("HOLD", symbol, 0.0, 0.0, 0.0, "insufficient_data")

    df = _compute_indicators(df, cfg)
    last = df.iloc[-1]
    sl_mul = cfg.get("stop_loss_pct", 1.0) / 100
    tgt_mul = cfg.get("target_pct", 2.0) / 100
    lookback = cfg["ema_crossover_lookback"]

    buy = (
        last["close"] > last["vwap"]
        and _ema_crossed_above(df, lookback)
        and last["rsi"] > cfg["rsi_entry_threshold"]
        and last["volume"] >= last["vol_sma"] * cfg["volume_multiplier"]
    )
    if buy:
        sl = round(last["close"] * (1 - sl_mul), 2)
        tgt = round(last["close"] * (1 + tgt_mul), 2)
        logger.info(f"{symbol}: BUY | close={last['close']} vwap={last['vwap']:.2f} rsi={last['rsi']:.1f}")
        return TradeSignal("BUY", symbol, last["close"], sl, tgt, "vwap_ema_rsi_volume")

    sell = (
        last["close"] < last["vwap"]
        and _ema_crossed_below(df, lookback)
        and last["rsi"] < (100 - cfg["rsi_entry_threshold"])
        and last["volume"] >= last["vol_sma"] * cfg["volume_multiplier"]
    )
    if sell:
        sl = round(last["close"] * (1 + sl_mul), 2)
        tgt = round(last["close"] * (1 - tgt_mul), 2)
        logger.info(f"{symbol}: SELL | close={last['close']} vwap={last['vwap']:.2f} rsi={last['rsi']:.1f}")
        return TradeSignal("SELL", symbol, last["close"], sl, tgt, "vwap_ema_rsi_volume_inverse")

    logger.info(f"{symbol}: HOLD — no signal")
    return TradeSignal("HOLD", symbol, 0.0, 0.0, 0.0, "no_conditions_met")


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


def should_exit(symbol: str, df: pd.DataFrame, position, cfg: dict) -> tuple[bool, str]:
    """
    Check EMA-reversal exit for an open position.
    Price-based exits (SL / target) are handled by PositionManager.
    `position` needs a .direction attribute ('BUY' or 'SELL').
    """
    if len(df) < _min_rows(cfg):
        return False, ""

    df = _compute_indicators(df, cfg)
    lookback = cfg["ema_crossover_lookback"]

    if position.direction == "BUY" and _ema_crossed_below(df, lookback):
        logger.info(f"{symbol}: EMA reversal — exiting BUY")
        return True, "ema_reversal"

    if position.direction == "SELL" and _ema_crossed_above(df, lookback):
        logger.info(f"{symbol}: EMA reversal — exiting SELL")
        return True, "ema_reversal"

    return False, ""
