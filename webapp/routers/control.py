"""
Control endpoints (Phase 2) — drive the bot subprocess.

All token-protected. Starting the bot while config is in LIVE mode requires an
explicit confirm flag (mirrors the CLI go-live gate: real orders never start on
an accidental tap).
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.ops import get_trading_mode
from webapp.auth import require_token
from webapp.supervisor import get_supervisor

router = APIRouter(prefix="/api/control", dependencies=[Depends(require_token)])


class StartRequest(BaseModel):
    confirm_live: bool = False


@router.get("/state")
def state() -> dict:
    return get_supervisor().state()


@router.post("/start")
def start(req: StartRequest | None = None) -> dict:
    req = req or StartRequest()
    if get_trading_mode() == "live" and not req.confirm_live:
        raise HTTPException(
            status_code=409,
            detail="Bot is in LIVE mode. Pass confirm_live=true to start real trading.",
        )
    return get_supervisor().start()


@router.post("/stop")
def stop() -> dict:
    return get_supervisor().stop()


@router.post("/pause")
def pause() -> dict:
    return get_supervisor().pause()


@router.post("/resume")
def resume() -> dict:
    return get_supervisor().resume()


@router.post("/squareoff")
def squareoff() -> dict:
    """Panic flatten: close all open positions now and pause new entries."""
    return get_supervisor().square_off()
