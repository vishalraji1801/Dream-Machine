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


@router.get("")
def list_strategies() -> dict:
    cfg = _load_cfg()
    return {
        "registered": sorted(STRATEGY_REGISTRY.keys()),
        "active": cfg.get("strategy", {}).get("name", "") or "",
        "allowed": cfg.get("ai", {}).get("allowed_strategies", []),
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
