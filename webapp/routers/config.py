"""
Config & risk editor (Phase 4).

GET  /api/config  -> editable groups + current values + bounds
PUT  /api/config  -> {updates: {section: {key: value}}}; validated + written
                     (comments preserved). Takes effect on the next bot start.
"""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from webapp.auth import require_token
from webapp.config_editor import apply_updates, read_config
from webapp.settings import get_settings

router = APIRouter(prefix="/api/config", dependencies=[Depends(require_token)])


class UpdateRequest(BaseModel):
    updates: dict[str, dict[str, Any]]


@router.get("")
def get_config() -> dict:
    return read_config(get_settings().config_path)


@router.put("")
def put_config(req: UpdateRequest) -> dict:
    try:
        groups = apply_updates(get_settings().config_path, req.updates)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"saved": True, "applies": "on next bot start", **groups}
