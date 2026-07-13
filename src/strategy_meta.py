"""
Strategy metadata (regime router, commit 2) — regime validity + pre-validated
parameter sets, declared in config (not code).

Each strategy carries a menu of parameter sets keyed by regime and a measured
`regime_fit` (filled by the analyst job, section 6). The one rule this module
enforces: a parameter set with `validated: false` is NEVER selectable in live or
paper — only in research/backtest. Level-1 adaptation *selects* a proven set; it
never invents numbers.
"""
import os
from dataclasses import dataclass, field
from typing import Optional

import yaml

from src.logger import get_logger
from src.regime import Regime

logger = get_logger("strategy_meta")

# Modes where an unvalidated parameter set may be used (research only).
RESEARCH_MODES = {"backtest", "research"}
_VALID_KEYS = {r.value for r in Regime} | {"default"}


@dataclass(frozen=True)
class ParamSet:
    params: dict
    validated: bool
    oos_ref: str = ""
    enabled: bool = True


@dataclass(frozen=True)
class RegimeFit:
    pf: float
    trades: int
    source: str = "ledger"


@dataclass(frozen=True)
class StrategyMeta:
    name: str
    regime_param_sets: dict = field(default_factory=dict)   # regime -> ParamSet
    regime_fit: dict = field(default_factory=dict)          # regime -> RegimeFit


def load_strategy_meta(data: dict) -> StrategyMeta:
    """Build a StrategyMeta from a parsed YAML/dict (see docs/specs section 3)."""
    name = data["name"]
    sets: dict = {}
    for regime, raw in (data.get("regime_param_sets") or {}).items():
        if regime not in _VALID_KEYS:
            logger.warning(f"{name}: unknown regime key '{regime}' in param sets — skipped")
            continue
        raw = dict(raw)
        enabled = bool(raw.pop("enabled", True))
        validated = bool(raw.pop("validated", False))
        oos_ref = str(raw.pop("oos_ref", ""))
        sets[regime] = ParamSet(params=raw, validated=validated, oos_ref=oos_ref,
                                enabled=enabled)
    fits: dict = {}
    for regime, raw in (data.get("regime_fit") or {}).items():
        if regime not in _VALID_KEYS:
            continue
        fits[regime] = RegimeFit(pf=float(raw.get("pf", 0.0)),
                                 trades=int(raw.get("trades", 0)),
                                 source=str(raw.get("source", "ledger")))
    return StrategyMeta(name=name, regime_param_sets=sets, regime_fit=fits)


def load_strategy_dir(path: str = "strategies") -> dict:
    """Load every <name>.yaml in a directory into {name: StrategyMeta}."""
    out: dict = {}
    if not os.path.isdir(path):
        return out
    for fn in sorted(os.listdir(path)):
        if not fn.endswith((".yaml", ".yml")):
            continue
        try:
            with open(os.path.join(path, fn), encoding="utf-8") as f:
                meta = load_strategy_meta(yaml.safe_load(f))
            out[meta.name] = meta
        except Exception as exc:
            logger.error(f"failed to load strategy meta {fn}: {exc}")
    return out


def _regime_key(regime) -> str:
    return regime.value if isinstance(regime, Regime) else str(regime)


def param_set_for(meta: StrategyMeta, regime, mode: str) -> Optional[ParamSet]:
    """
    Select the parameter set for `regime` (falling back to 'default'), applying the
    governing rule. Returns None when the strategy should NOT run in this regime:
    disabled set, no set/default, or an unvalidated set outside research mode.
    """
    key = _regime_key(regime)
    ps = meta.regime_param_sets.get(key) or meta.regime_param_sets.get("default")
    if ps is None or not ps.enabled:
        return None
    if not ps.validated and mode not in RESEARCH_MODES:
        logger.debug(f"{meta.name}: unvalidated set for {key} blocked in mode '{mode}'")
        return None
    return ps


def bounded_param_set(meta: StrategyMeta, regime, mode: str,
                      bounds: Optional[dict] = None, on_alert=None) -> Optional[ParamSet]:
    """
    Like param_set_for, but every value must pass the hard bounds. An out-of-bounds
    set is rejected and we fall back to the strategy's `default` set (if that is
    valid and in bounds); otherwise the strategy is disabled. Every fallback/reject
    fires an alert. This is the enforcement point the spec requires.
    """
    from src.adaptive_bounds import validate_params

    ps = param_set_for(meta, regime, mode)
    if ps is None:
        return None
    err = validate_params(ps.params, bounds)
    if err is None:
        return ps

    key = _regime_key(regime)
    if on_alert:
        on_alert(f"{meta.name} {key}: {err} — falling back to default")
    logger.warning(f"{meta.name} {key}: adaptive param {err} — falling back to default")

    default = meta.regime_param_sets.get("default")
    if (default and default.enabled and (default.validated or mode in RESEARCH_MODES)
            and validate_params(default.params, bounds) is None):
        return default

    if on_alert:
        on_alert(f"{meta.name} {key}: default also out of bounds — strategy disabled")
    logger.error(f"{meta.name} {key}: no in-bounds param set — strategy disabled")
    return None


def fit_for(meta: StrategyMeta, regime, min_trades: int = 30) -> Optional[RegimeFit]:
    """The measured fit for a regime, or None if absent / below the sample floor
    (the router treats None as neutral, never as an edge)."""
    fit = meta.regime_fit.get(_regime_key(regime))
    if fit is None or fit.trades < min_trades:
        return None
    return fit
