"""
Regime classifier (regime router, commit 1) — PURE.

Turns a MarketState into a committed Regime with a confidence and an anti-whipsaw
dwell filter. No I/O, no now() side effects (`now` is passed for traceability/
persistence only). Identical bytes in backtest / paper / live.

Thresholds in RegimeConfig are SWEEP CANDIDATES — placeholders until validated on
out-of-sample data. Nothing here fits or deploys an unvalidated parameter; it only
labels the current state.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from src.market_state import MarketState


class Regime(Enum):
    STRONG_TREND_UP = "STRONG_TREND_UP"
    STRONG_TREND_DOWN = "STRONG_TREND_DOWN"
    RANGE = "RANGE"
    HIGH_VOL_CHOP = "HIGH_VOL_CHOP"
    QUIET = "QUIET"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class RegimeConfig:
    adx_trend: float = 25.0        # ADX at/above -> trending
    adx_range: float = 20.0        # ADX below -> non-trending
    atr_pct_high: float = 1.0      # ATR% at/above -> high volatility
    atr_pct_low: float = 0.3       # ATR% at/below -> quiet
    bb_width_low_pctile: float = 0.20   # compression for QUIET
    ema_slope_min: float = 0.0     # slope sign decides trend side
    min_dwell_bars: int = 3        # bars a new regime must persist before commit
    min_bars: int = 60             # below this -> UNKNOWN (insufficient data)


@dataclass(frozen=True)
class RegimeState:
    regime: Regime
    confidence: float
    since_bars: int
    inputs: dict
    config_version: str = ""
    # hysteresis machine state (candidate awaiting the dwell threshold)
    pending_regime: Regime = Regime.UNKNOWN
    pending_bars: int = 0


def _raw_regime(s: MarketState, cfg: RegimeConfig) -> Regime:
    """Instantaneous label from the state, before hysteresis."""
    trending = s.adx >= cfg.adx_trend
    non_trending = s.adx < cfg.adx_range
    if trending:
        if s.close > s.ema_slow and s.ema_slope > cfg.ema_slope_min:
            return Regime.STRONG_TREND_UP
        if s.close < s.ema_slow and s.ema_slope < -cfg.ema_slope_min:
            return Regime.STRONG_TREND_DOWN
        # strong ADX but ambiguous side -> treat as range-ish
    if s.atr_pct >= cfg.atr_pct_high and non_trending:
        return Regime.HIGH_VOL_CHOP
    if s.atr_pct <= cfg.atr_pct_low and s.bb_width_pctile <= cfg.bb_width_low_pctile:
        return Regime.QUIET
    if non_trending:
        return Regime.RANGE
    return Regime.UNKNOWN


def _confidence(regime: Regime, s: MarketState, cfg: RegimeConfig) -> float:
    """0..1 — how far the deciding inputs clear their thresholds."""
    def clamp(x):
        return max(0.0, min(1.0, x))

    if regime in (Regime.STRONG_TREND_UP, Regime.STRONG_TREND_DOWN):
        # margin of ADX over the trend threshold (25 -> 0, 45+ -> 1)
        return clamp((s.adx - cfg.adx_trend) / max(cfg.adx_trend, 1e-9))
    if regime == Regime.HIGH_VOL_CHOP:
        return clamp((s.atr_pct - cfg.atr_pct_high) / max(cfg.atr_pct_high, 1e-9))
    if regime == Regime.QUIET:
        return clamp((cfg.atr_pct_low - s.atr_pct) / max(cfg.atr_pct_low, 1e-9))
    if regime == Regime.RANGE:
        # clearer range the lower ADX sits under the range threshold
        return clamp((cfg.adx_range - s.adx) / max(cfg.adx_range, 1e-9))
    return 0.0


def classify(state: MarketState, prev: Optional[RegimeState],
             cfg: RegimeConfig, now=None) -> RegimeState:
    """
    Commit a regime with hysteresis. A regime different from the committed one is
    held as a *candidate* and only replaces it after it persists `min_dwell_bars`
    consecutive bars — the anti-whipsaw guard. `now` is accepted for traceability
    only (no clock is read here).
    """
    inputs = {"adx": round(state.adx, 3), "atr_pct": round(state.atr_pct, 4),
              "bb_width_pctile": round(state.bb_width_pctile, 4),
              "ema_slope": round(state.ema_slope, 6), "close": state.close,
              "ema_slow": round(state.ema_slow, 4), "breadth": state.breadth,
              "n_bars": state.n_bars}
    cv = state.config_version

    if state.n_bars < cfg.min_bars:
        return RegimeState(Regime.UNKNOWN, 0.0, 1, inputs, cv,
                           pending_regime=Regime.UNKNOWN, pending_bars=0)

    raw = _raw_regime(state, cfg)

    if prev is None:
        return RegimeState(raw, _confidence(raw, state, cfg), 1, inputs, cv,
                           pending_regime=raw, pending_bars=0)

    if raw == prev.regime:
        # candidate matches committed -> reset the pending machine, extend dwell
        return RegimeState(prev.regime, _confidence(prev.regime, state, cfg),
                           prev.since_bars + 1, inputs, cv,
                           pending_regime=prev.regime, pending_bars=0)

    # raw differs from the committed regime -> advance the candidate streak
    if raw == prev.pending_regime:
        pending_bars = prev.pending_bars + 1
    else:
        pending_bars = 1

    if pending_bars >= cfg.min_dwell_bars:
        # candidate has persisted long enough -> commit it
        return RegimeState(raw, _confidence(raw, state, cfg), 1, inputs, cv,
                           pending_regime=raw, pending_bars=0)

    # keep the committed regime; remember the candidate
    return RegimeState(prev.regime, _confidence(prev.regime, state, cfg),
                       prev.since_bars + 1, inputs, cv,
                       pending_regime=raw, pending_bars=pending_bars)
