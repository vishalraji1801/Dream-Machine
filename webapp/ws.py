"""
Live WebSocket — pushes a state snapshot to the UI on an interval so the
dashboard updates without polling.

Browsers can't set headers on a WebSocket handshake, so the token is passed as a
query param: ws://host/ws/live?token=<token>. Same token, same constant-time
compare as the REST guard.
"""
import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.logger import get_logger
from webapp import stores
from webapp.auth import token_is_valid
from webapp.supervisor import get_supervisor

logger = get_logger("ws")
router = APIRouter()

PUSH_INTERVAL_SECONDS = 2.0


def _snapshot() -> dict:
    state = stores.read_state()
    sup = get_supervisor().state()
    return {
        "type": "snapshot",
        "running": sup["running"],
        "mode": sup["mode"],
        "positions": state["positions"],
        "daily_pnl": state["daily_pnl"],
        "trades_today": state["trades_today"],
        "stale": state["stale"],
    }


@router.websocket("/ws/live")
async def live(ws: WebSocket) -> None:
    token = ws.query_params.get("token", "")
    if not token_is_valid(token):
        await ws.close(code=1008)  # policy violation
        return
    await ws.accept()
    try:
        while True:
            await ws.send_json(_snapshot())
            await asyncio.sleep(PUSH_INTERVAL_SECONDS)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # keep a client error from bubbling into the server
        logger.warning(f"ws live closed: {exc}")
