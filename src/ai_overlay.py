"""
AI overlay — the safety sandbox for the scheduled Claude strategist.

Claude *proposes* by writing config/ai_overlay.yaml; deterministic code *disposes*.
The bot loads the overlay at startup and validates every field against hard bounds
from the `ai:` config section. Anything out of bounds, unknown, or unparseable makes
the WHOLE overlay rejected — the bot falls back to config.yaml and alerts on Telegram.

An LLM never touches the live order path. It can only nudge a small, whitelisted set
of knobs, and only within limits you define here.
"""
import os
from typing import Optional

import yaml

from src.logger import get_logger

logger = get_logger("ai_overlay")

# Numeric strategy params the tuner/strategist may adjust, with hard bounds.
# Anything outside these ranges rejects the WHOLE overlay.
_STRATEGY_BOUNDS = {
    "rsi_entry_threshold": (50, 80),
    "volume_multiplier": (1.0, 5.0),
    "vwap_stretch_pct": (0.5, 4.0),
    "rsi_overbought": (60, 90),
    "rsi_oversold": (10, 40),
    "supertrend_period": (5, 30),
    "supertrend_mult": (1.0, 5.0),
    # strategy-library tunables (E-005 / E-003 / E-008) — sweepable within bounds
    "bb_ma_period": (150, 250),
    "bb_period": (10, 40),
    "bb_std": (1.5, 3.5),
    "bb_buy_limit_offset_pct": (0.0, 5.0),
    "bb_atr_stop_mult": (2.0, 5.0),
    "donchian_lookback": (50, 300),
    "donchian_atr_mult": (2.0, 8.0),
    "orb_max_stop_cap_pts": (10, 100),
    "orb_r_multiple": (1.0, 4.0),
    "atr_period": (5, 30),
    "atr_sl_mult": (0.5, 4.0),
    "atr_target_mult": (1.0, 8.0),
    "ec_fast": (5, 100),
    "ec_slow": (10, 300),
    "rsi_rev_period": (2, 14),
    "rsi_rev_oversold": (5, 30),
    "rsi_rev_overbought": (70, 95),
    "pullback_ema": (10, 100),
    "pullback_tol_pct": (0.1, 1.0),
    "br_lookback": (5, 60),
    "br_tol_pct": (0.1, 1.0),
    "macd_div_lookback": (10, 40),
    "sr_lookback": (10, 60),
    "sr_tol_pct": (0.1, 1.0),
    "pa_lookback": (10, 40),
    "pa_tol_pct": (0.1, 1.0),
    "mtf_long_ema": (30, 200),
    "mtf_short_ema": (5, 50),
    "smc_lookback": (5, 40),
}
_ORB_END_ALLOWED = {"09:30", "09:45", "10:00"}
_MTF_TF_ALLOWED = {"30min", "1hr"}
_MTF_RULE_ALLOWED = {"ema_trend", "supertrend_dir"}

# Only these top-level keys may be adjusted by an overlay. Capital, position caps,
# circuit breakers, product type, watchlist etc. are deliberately NOT adjustable.
_ADJUSTABLE = {
    "strategy": {"name", "regime_filter_enabled", "orb_end", "sl_mode",
                 "mtf_enabled", "mtf_higher_tf", "mtf_rule",
                 *_STRATEGY_BOUNDS},
    "risk": {"stop_loss_pct", "target_pct", "trailing_sl_enabled",
             "max_trades_per_day"},
    "trading": {"entry_start_time", "entry_end_time"},
}


def load_overlay(cfg: dict) -> tuple[Optional[dict], Optional[str]]:
    """
    Return (validated_overlay, error). On success error is None. On any problem
    the overlay is None and error is a human-readable reason for the alert.
    Returns (None, None) when no overlay file exists (the normal case).
    """
    ai = cfg.get("ai", {})
    if not ai.get("overlay_enabled"):
        return None, None

    path = ai.get("overlay_path", "config/ai_overlay.yaml")
    if not os.path.exists(path):
        return None, None

    try:
        with open(path) as f:
            raw = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError) as exc:
        return None, f"overlay unreadable: {exc}"

    if not isinstance(raw, dict):
        return None, "overlay is not a mapping"

    overlay = {k: v for k, v in raw.items() if k != "meta"}
    err = _validate(overlay, cfg)
    if err:
        return None, err
    return overlay, None


def apply_overlay(cfg: dict, overlay: dict) -> dict:
    """Merge a validated overlay's fields onto a copy of cfg. Non-mutating."""
    import copy
    merged = copy.deepcopy(cfg)
    for section, fields in overlay.items():
        merged.setdefault(section, {})
        for key, value in fields.items():
            merged[section][key] = value
    return merged


def _validate(overlay: dict, cfg: dict) -> Optional[str]:
    ai = cfg.get("ai", {})
    for section, fields in overlay.items():
        if section not in _ADJUSTABLE:
            return f"section '{section}' is not adjustable by overlay"
        if not isinstance(fields, dict):
            return f"section '{section}' must be a mapping"
        for key, value in fields.items():
            if key not in _ADJUSTABLE[section]:
                return f"field '{section}.{key}' is not adjustable"

    # Bounded numeric / enum checks
    strat = overlay.get("strategy", {})
    if "name" in strat:
        allowed = ai.get("allowed_strategies", [])
        if strat["name"] not in allowed:
            return f"strategy.name '{strat['name']}' not in allowed_strategies"
    if "orb_end" in strat and str(strat["orb_end"]) not in _ORB_END_ALLOWED:
        return f"strategy.orb_end '{strat['orb_end']}' not in {sorted(_ORB_END_ALLOWED)}"
    if "sl_mode" in strat and strat["sl_mode"] not in ("pct", "atr"):
        return "strategy.sl_mode must be 'pct' or 'atr'"
    if "mtf_enabled" in strat and not isinstance(strat["mtf_enabled"], bool):
        return "strategy.mtf_enabled must be true/false"
    if "mtf_higher_tf" in strat and strat["mtf_higher_tf"] not in _MTF_TF_ALLOWED:
        return f"strategy.mtf_higher_tf not in {sorted(_MTF_TF_ALLOWED)}"
    if "mtf_rule" in strat and strat["mtf_rule"] not in _MTF_RULE_ALLOWED:
        return f"strategy.mtf_rule not in {sorted(_MTF_RULE_ALLOWED)}"
    for key, (lo, hi) in _STRATEGY_BOUNDS.items():
        if key in strat:
            value = strat[key]
            if not isinstance(value, (int, float)) or not (lo <= value <= hi):
                return f"strategy.{key} out of bounds ({lo}-{hi})"

    risk = overlay.get("risk", {})
    if "stop_loss_pct" in risk and not (
            ai.get("min_stop_loss_pct", 0.5) <= risk["stop_loss_pct"] <= ai.get("max_stop_loss_pct", 2.0)):
        return "risk.stop_loss_pct out of bounds"
    if "target_pct" in risk and not (
            ai.get("min_target_pct", 0.5) <= risk["target_pct"] <= ai.get("max_target_pct", 5.0)):
        return "risk.target_pct out of bounds"
    if "max_trades_per_day" in risk and not (1 <= risk["max_trades_per_day"] <= 20):
        return "risk.max_trades_per_day out of bounds (1-20)"

    trading = overlay.get("trading", {})
    for key in ("entry_start_time", "entry_end_time"):
        if key in trading and not _within_market_hours(trading[key], cfg):
            return f"trading.{key} '{trading[key]}' outside market hours"

    return None


def _within_market_hours(value: str, cfg: dict) -> bool:
    try:
        h, m = map(int, str(value).split(":"))
    except (ValueError, AttributeError):
        return False
    minutes = h * 60 + m
    t = cfg["trading"]
    open_h, open_m = map(int, t["market_open"].split(":"))
    close_h, close_m = map(int, t["market_close"].split(":"))
    return open_h * 60 + open_m <= minutes <= close_h * 60 + close_m
