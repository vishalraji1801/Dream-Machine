"""
Strategy manager (Phase 5).

GET  /api/strategies         -> registered strategies + the active one
PUT  /api/strategies/active  -> set the active strategy (must be registered, or
                                empty for the clean-slate no-trade default)

The registry is currently empty by design (real strategies are being added); this
screen is the scaffolding that lights up the moment one is registered.
"""
import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.strategy import STRATEGY_REGISTRY
from webapp.auth import require_token
from webapp.config_editor import apply_updates
from webapp.settings import get_settings

router = APIRouter(prefix="/api/strategies", dependencies=[Depends(require_token)])


class ActiveRequest(BaseModel):
    name: str


def _load_cfg() -> dict:
    with open(get_settings().config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _swing_state(cfg: dict) -> dict:
    """The swing sleeve's edges with validated/benched status + fit PF, read live
    from strategies/*.yaml — reflects the post-gauntlet reality."""
    import os

    from src.regime import Regime
    from src.strategy_meta import load_strategy_dir, param_set_for
    from src.swing_engine import SWING_STRATEGIES

    cfg_path = os.path.abspath(get_settings().config_path)
    strat_dir = os.path.join(os.path.dirname(os.path.dirname(cfg_path)), "strategies")
    try:
        metas = load_strategy_dir(strat_dir)
    except Exception:
        metas = {}
    edges = []
    for name in SWING_STRATEGIES:
        m = metas.get(name)
        if m is None:
            continue
        validated = any(param_set_for(m, r, "paper") is not None for r in Regime)
        pfs = [getattr(f, "pf", None) for f in getattr(m, "regime_fit", {}).values()]
        pfs = [p for p in pfs if p is not None]
        edges.append({"name": name, "validated": validated,
                      "pf": max(pfs) if pfs else None})
    edges.sort(key=lambda e: (not e["validated"], -(e["pf"] or 0)))
    return {"enabled": cfg.get("swing", {}).get("enabled", False), "edges": edges}


@router.get("")
def list_strategies() -> dict:
    cfg = _load_cfg()
    return {
        "registered": sorted(STRATEGY_REGISTRY.keys()),
        "active": cfg.get("strategy", {}).get("name", "") or "",
        "allowed": cfg.get("overlay", {}).get("allowed_strategies", []),
        "intraday_enabled": cfg.get("intraday", {}).get("enabled", True),
        "swing": _swing_state(cfg),
    }


@router.put("/active")
def set_active(req: ActiveRequest) -> dict:
    name = req.name.strip()
    if name and name not in STRATEGY_REGISTRY:
        raise HTTPException(
            status_code=422,
            detail=f"'{name}' is not registered. Registered: {sorted(STRATEGY_REGISTRY) or '(none)'}",
        )
    apply_updates(get_settings().config_path, {"strategy": {"name": name}})
    return {"active": name, "applies": "on next bot start"}
