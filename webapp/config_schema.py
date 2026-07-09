"""
Editable-config schema — the single source of truth for what the Settings UI can
change and the bounds the backend enforces.

Only fields listed here are editable; everything else in config.yaml is left
untouched (and comments are preserved on write). Each field carries enough
metadata for the UI to render the right control and for the server to validate.

`key` uses dotted paths for nested values, e.g. "mtf_confirm.enabled".
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    type: str  # number | bool | select | time | text
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None
    unit: str = ""
    options: tuple = ()
    help: str = ""


@dataclass(frozen=True)
class Group:
    section: str          # top-level config.yaml key
    label: str
    fields: list = field(default_factory=list)


SCHEMA: list[Group] = [
    Group("risk", "Risk", [
        Field("total_capital", "Total capital", "number", 10_000, 100_000_000, 10_000, "₹"),
        Field("max_risk_per_trade_pct", "Risk per trade", "number", 0.1, 5, 0.1, "%"),
        Field("max_open_positions", "Max open positions", "number", 1, 20, 1),
        Field("max_position_size_pct", "Max position size", "number", 1, 100, 1, "%"),
        Field("order_value_cap", "Order value cap", "number", 1_000, 10_000_000, 1_000, "₹"),
        Field("stop_loss_pct", "Stop loss", "number", 0.1, 10, 0.1, "%"),
        Field("target_pct", "Target", "number", 0.1, 20, 0.1, "%"),
        Field("min_risk_reward", "Min risk:reward", "number", 0.5, 10, 0.5),
        Field("trailing_sl_enabled", "Trailing stop", "bool"),
        Field("trailing_sl_activation_pct", "Trail activation", "number", 0.1, 10, 0.1, "%"),
        Field("trailing_sl_step_pct", "Trail step", "number", 0.1, 5, 0.1, "%"),
        Field("max_daily_loss", "Max daily loss", "number", 0, 1_000_000, 1_000, "₹"),
        Field("max_trades_per_day", "Max trades/day", "number", 1, 100, 1),
        Field("max_consecutive_api_errors", "Max API errors", "number", 1, 20, 1),
        Field("min_margin_threshold", "Min margin", "number", 0, 1_000_000, 1_000, "₹"),
        Field("max_spread_pct", "Max spread", "number", 0.01, 2, 0.01, "%"),
        Field("max_positions_per_sector", "Max per sector", "number", 1, 20, 1),
        Field("max_giveback_from_peak", "Max giveback", "number", 0, 1_000_000, 500, "₹",
              help="Halt if daily P&L falls this far from its peak (0 = off)"),
    ]),
    Group("strategy", "Strategy", [
        Field("name", "Active strategy", "text",
              help="Must match a registered strategy; empty = no trades (clean slate)"),
        Field("sl_mode", "SL sizing", "select", options=("pct", "atr")),
        Field("ema_fast", "EMA fast", "number", 2, 200, 1),
        Field("ema_slow", "EMA slow", "number", 2, 200, 1),
        Field("rsi_period", "RSI period", "number", 2, 50, 1),
        Field("volume_sma_period", "Volume SMA period", "number", 2, 100, 1),
        Field("volume_multiplier", "Volume multiplier", "number", 0.5, 5, 0.1, "x"),
        Field("atr_period", "ATR period", "number", 5, 50, 1),
        Field("atr_sl_mult", "ATR SL mult", "number", 0.5, 5, 0.1, "x"),
        Field("atr_target_mult", "ATR target mult", "number", 0.5, 10, 0.1, "x"),
        Field("regime_filter_enabled", "Regime filter", "bool"),
        Field("regime_ema", "Regime EMA", "number", 5, 100, 1),
        Field("regime_band_pct", "Regime band", "number", 0, 2, 0.05, "%"),
        Field("mtf_confirm.enabled", "MTF confirmation", "bool"),
        Field("mtf_confirm.higher_tf", "MTF higher TF", "select", options=("30min", "1hr")),
        Field("mtf_confirm.rule", "MTF rule", "select", options=("ema_trend", "supertrend_dir")),
        Field("mtf_confirm.ema", "MTF EMA", "number", 5, 200, 1),
    ]),
    Group("trading", "Timing", [
        Field("timeframe", "Timeframe", "select",
              options=("5minute", "15minute", "30minute", "60minute")),
        Field("entry_start_time", "Entry start", "time"),
        Field("entry_end_time", "Entry end", "time"),
        Field("square_off_time", "Square off", "time"),
    ]),
    Group("scheduler", "Scheduler", [
        Field("cycle_interval_seconds", "Cycle interval", "number", 30, 3600, 30, "s"),
        Field("heartbeat_interval_minutes", "Heartbeat", "number", 5, 240, 5, "min"),
        Field("max_tick_age_seconds", "Max tick age", "number", 5, 120, 5, "s"),
    ]),
]


def field_index() -> dict[str, tuple[str, Field]]:
    """{'risk.total_capital' -> (section, Field)} for O(1) validation lookup."""
    out: dict[str, tuple[str, Field]] = {}
    for g in SCHEMA:
        for f in g.fields:
            out[f"{g.section}.{f.key}"] = (g.section, f)
    return out
