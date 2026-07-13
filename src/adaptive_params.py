"""
Level-2 adaptive parameters (regime router, commit 3) — PURE formula scaling.

These need no validation surface because they don't fit anything: they scale by
construction with volatility, so they stay sane across regimes automatically.
Preferred over per-regime tuned values wherever possible — robustness for free.

  - ATR-unit stops/targets  -> auto-widen when volatility rises
  - 1/ATR position size      -> constant rupee risk across regimes
  - relative RVOL            -> volume judged vs its time-of-day baseline, not absolute

All functions are pure (numbers in, numbers out). `atr` here is MarketState.atr.
"""
from typing import Optional


def atr_stop_target(price: float, direction: str, atr: float,
                    sl_mult: float, target_mult: float) -> tuple[float, float]:
    """Stop/target placed in ATR units. Widens with volatility automatically."""
    sl_dist = sl_mult * atr
    tgt_dist = target_mult * atr
    if direction == "BUY":
        return round(price - sl_dist, 2), round(price + tgt_dist, 2)
    return round(price + sl_dist, 2), round(price - tgt_dist, 2)


def atr_position_size(capital: float, risk_pct: float, atr: float, sl_mult: float,
                      price: Optional[float] = None,
                      max_position_value: Optional[float] = None) -> int:
    """
    Size so that a stop-out loses a CONSTANT rupee amount (risk_pct of capital),
    regardless of regime: qty = risk_amount / (sl_mult * ATR). Higher volatility ->
    wider stop -> smaller size. Optionally capped by a max position value.
    """
    sl_dist = sl_mult * atr
    if sl_dist <= 0 or capital <= 0 or risk_pct <= 0:
        return 0
    risk_amount = capital * risk_pct / 100.0
    qty = int(risk_amount / sl_dist)
    if price and max_position_value and price > 0:
        qty = min(qty, int(max_position_value / price))
    return max(qty, 0)


def relative_volume(cum_vol_now: float, baseline_cum_vol: float) -> Optional[float]:
    """Today's cumulative volume vs the time-of-day baseline. None if no baseline."""
    if not baseline_cum_vol or baseline_cum_vol <= 0:
        return None
    return round(cum_vol_now / baseline_cum_vol, 4)


def volume_gate(rvol_value: Optional[float], min_rvol: float) -> bool:
    """A relative-volume gate: pass only when RVOL is known and clears the floor.
    Unknown RVOL fails closed (no absolute-volume fallback)."""
    return rvol_value is not None and rvol_value >= min_rvol
