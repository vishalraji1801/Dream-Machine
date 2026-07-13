"""
Strategy engine — framework only.

The strategy implementations have been removed (clean slate for real strategies).
What remains is the pluggable machinery + a reusable indicator toolkit:

  - TradeSignal: the (direction, entry, stop_loss, target, reason) a strategy returns
  - STRATEGY_REGISTRY: {name -> fn}; register a strategy to make it selectable
    everywhere (backtest, paper, live, autotuner) — it needs no other wiring
  - generate_signal(symbol, df, cfg): dispatches on cfg['name'], applies the MTF gate
  - indicator toolkit: _compute_indicators, _atr, _sl_target, _ema_col,
    _supertrend_dir, EMA/crossover helpers, market_regime
  - multi-timeframe confirmation gate (higher_tf_trend / _apply_mtf_gate)

To add a strategy, write `def my_strategy(symbol, df, cfg) -> TradeSignal:` and add
it to STRATEGY_REGISTRY. Use `_sl_target(df, entry, direction, cfg)` for SL/target.
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


# ── Indicator toolkit (building blocks for real strategies) ───────────────────

def _compute_indicators(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Append VWAP, EMA fast/slow, RSI, and Volume SMA columns (returns a copy)."""
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
    Stop-loss and target for an entry. Two modes:
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


def _hold(symbol: str, reason: str) -> TradeSignal:
    return TradeSignal("HOLD", symbol, 0.0, 0.0, 0.0, reason)


def _ema_col(df: pd.DataFrame, window: int):
    return EMAIndicator(df["close"], window=window).ema_indicator()


def _crossed_above(a, b) -> bool:
    """Series a crossed above series b on the latest bar."""
    return bool(a.iloc[-2] <= b.iloc[-2] and a.iloc[-1] > b.iloc[-1])


def _crossed_below(a, b) -> bool:
    return bool(a.iloc[-2] >= b.iloc[-2] and a.iloc[-1] < b.iloc[-1])


def _supertrend_dir(df: pd.DataFrame, period: int, mult: float) -> Optional[list]:
    """Per-candle Supertrend direction (+1 up, -1 down), or None. Used by the MTF
    gate's 'supertrend_dir' rule and available to strategies."""
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


# ── Registry & dispatcher ─────────────────────────────────────────────────────

# Empty by design — strategies were removed for a clean slate. Register real
# strategies here: {"my_strategy": my_strategy_fn}. Each fn is
# (symbol, df, cfg) -> TradeSignal and is then usable in backtest/paper/live and
# by the auto-tuner (add a grid to auto_tuner.DEFAULT_GRIDS).
STRATEGY_REGISTRY: dict = {}


def generate_signal(symbol: str, df: pd.DataFrame, cfg: dict) -> TradeSignal:
    """
    Dispatch to the strategy named by cfg['name'], then apply the optional
    multi-timeframe confirmation gate. Returns HOLD if no strategy is registered
    under that name (the clean-slate default — the bot simply takes no trades).
    """
    strategy_fn = STRATEGY_REGISTRY.get(cfg.get("name"))
    if strategy_fn is None:
        return _hold(symbol, "no_strategy")
    signal = strategy_fn(symbol, df, cfg)
    return _apply_mtf_gate(symbol, df, cfg, signal)


# ── Multi-timeframe confirmation gate ─────────────────────────────────────────

def higher_tf_trend(higher_df: pd.DataFrame, cfg: dict) -> Optional[str]:
    """Trend on the higher timeframe: 'UP' | 'DOWN' | 'NEUTRAL' | None (not ready).
    Rule 'ema_trend' (default): price vs a rising/falling EMA.
    Rule 'supertrend_dir': supertrend line direction."""
    rule = cfg.get("rule", "ema_trend")
    if rule == "supertrend_dir":
        direction = _supertrend_dir(higher_df, cfg.get("supertrend_period", 10),
                                    cfg.get("supertrend_mult", 3.0))
        if direction is None:
            return None
        return "UP" if direction[-1] == 1 else "DOWN"
    window = cfg.get("ema", 50)
    if higher_df is None or len(higher_df) < window + 3:
        return None
    ema = _ema_col(higher_df, window)
    close = float(higher_df["close"].iloc[-1])
    e_now, e_prev = float(ema.iloc[-1]), float(ema.iloc[-3])
    if close > e_now and e_now >= e_prev:
        return "UP"
    if close < e_now and e_now <= e_prev:
        return "DOWN"
    return "NEUTRAL"


def _apply_mtf_gate(symbol: str, df: pd.DataFrame, cfg: dict,
                    signal: TradeSignal) -> TradeSignal:
    # Nested config block, overridable by flat keys (so the bounded AI overlay
    # and the auto-tuner can toggle/tune MTF through simple whitelisted fields).
    mtf = dict(cfg.get("mtf_confirm", {}))
    for flat, key in (("mtf_enabled", "enabled"), ("mtf_higher_tf", "higher_tf"),
                      ("mtf_rule", "rule")):
        if flat in cfg:
            mtf[key] = cfg[flat]
    if not mtf.get("enabled") or signal.direction == "HOLD":
        return signal

    higher_tf = mtf.get("higher_tf", "1hr")
    from src.timeframe import resample_ohlcv
    if "timestamp" not in df.columns:
        return _hold(symbol, "mtf_no_timestamp")       # can't resample — fail-closed
    higher = resample_ohlcv(df, higher_tf)
    trend = higher_tf_trend(higher, mtf)
    if trend is None:
        return _hold(symbol, "mtf_not_ready")           # warm-up: fail-closed
    agree = (signal.direction == "BUY" and trend == "UP") or \
            (signal.direction == "SELL" and trend == "DOWN")
    if not agree:
        logger.info(f"{symbol}: {signal.direction} vetoed by {higher_tf} trend {trend}")
        return TradeSignal("HOLD", symbol, signal.entry_price, signal.stop_loss,
                           signal.target, f"mtf_veto:{signal.direction}:{trend}")
    return signal


# ── Market regime ─────────────────────────────────────────────────────────────

Regime = Literal["BULLISH", "BEARISH", "NEUTRAL"]


def market_regime(df: pd.DataFrame, cfg: dict) -> Regime:
    """
    Classify the index trend so entries can align with the broader market.
    BULLISH above the EMA + band, BEARISH below, NEUTRAL inside (choppy).
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


# ── Register the strategy library ─────────────────────────────────────────────
# Imported last so the toolkit above is fully defined; strategy_library imports
# these helpers, so this avoids a circular import.
from src.strategy_library import REGISTRY as _LIBRARY   # noqa: E402
STRATEGY_REGISTRY.update(_LIBRARY)
