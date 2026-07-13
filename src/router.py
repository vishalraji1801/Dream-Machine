"""
Regime router (regime router, commit 4) — PURE.

Given the committed regime and each strategy's metadata, decide which strategies
run and with what weight. Weights are proportional to measured edge (regime_fit.pf)
and split a risk budget that is scaled by regime confidence and capped by the
premarket ceiling. Adaptation may only *downsize or disable* — it can never exceed
the premarket-sanctioned allocation.

"Trade nothing" is a first-class outcome: if no strategy has a positive edge
(pf > min_fit_pf) in this regime, the router returns an empty list. Sitting out is
often the edge.
"""
from dataclasses import dataclass, field
from typing import Optional

from src.regime import Regime, RegimeState
from src.strategy_meta import ParamSet, StrategyMeta, fit_for, param_set_for


@dataclass(frozen=True)
class PremarketAllocation:
    ceiling: float = 1.0          # max total weight the day permits (intraday can only lower)
    caps: dict = field(default_factory=dict)   # optional per-strategy weight caps


@dataclass(frozen=True)
class RouterConfig:
    mode: str = "live"            # live | paper | backtest | research
    min_fit_pf: float = 1.0       # a strategy is an "edge" only above this
    min_trades: int = 30          # small-sample floor for regime_fit
    max_weight_change: float = 0.2   # per-cycle weight hysteresis


@dataclass(frozen=True)
class ActiveStrategy:
    name: str
    param_set: ParamSet
    weight: float
    fit_pf: float
    regime: str
    oos_ref: str = ""


def routing_records(active: list) -> list:
    """Serialize an ActiveStrategy list for ledger persistence (JSON-friendly)."""
    return [{"name": a.name, "weight": a.weight, "fit_pf": a.fit_pf,
             "regime": a.regime, "oos_ref": a.oos_ref} for a in active]


def route(regime: RegimeState, strategies: list[StrategyMeta],
          premarket: PremarketAllocation, cfg: RouterConfig,
          prev_weights: Optional[dict] = None) -> list[ActiveStrategy]:
    if regime.regime is Regime.UNKNOWN:
        return []

    # eligible = has a usable (validated-in-mode, enabled) set AND enough-sample fit
    eligible = []
    for meta in strategies:
        ps = param_set_for(meta, regime.regime, cfg.mode)
        if ps is None:
            continue
        fit = fit_for(meta, regime.regime, cfg.min_trades)
        if fit is None:            # insufficient data -> neutral, never a guess
            continue
        eligible.append((meta, ps, fit))

    if not eligible:
        return []
    if max(fit.pf for _, _, fit in eligible) <= cfg.min_fit_pf:
        return []                  # no positive edge anywhere -> trade nothing

    # split a confidence-scaled risk budget by edge (pf) ratio
    sum_pf = sum(fit.pf for _, _, fit in eligible)
    total_alloc = premarket.ceiling * max(0.0, min(1.0, regime.confidence))
    targets = {meta.name: (fit.pf / sum_pf) * total_alloc for meta, _, fit in eligible}

    # per-strategy caps (only lower)
    for name in list(targets):
        cap = premarket.caps.get(name)
        if cap is not None:
            targets[name] = min(targets[name], cap)

    # weight hysteresis: don't let any weight jump more than max_weight_change/cycle
    if prev_weights:
        d = cfg.max_weight_change
        for name in list(targets):
            prev = prev_weights.get(name, 0.0)
            targets[name] = max(prev - d, min(prev + d, targets[name]))

    # fail-safe: total must never exceed the premarket ceiling
    total = sum(targets.values())
    if total > premarket.ceiling and total > 0:
        scale = premarket.ceiling / total
        targets = {n: w * scale for n, w in targets.items()}

    out = []
    for meta, ps, fit in eligible:
        w = round(targets[meta.name], 6)
        if w <= 0:
            continue
        out.append(ActiveStrategy(name=meta.name, param_set=ps, weight=w,
                                  fit_pf=fit.pf, regime=regime.regime.value,
                                  oos_ref=ps.oos_ref))
    return out
