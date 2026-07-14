"""
Read-only monitoring endpoints (Phase 1) — the data the dashboard renders.

All are token-protected. Control endpoints (start/stop/pause/square-off) and the
live WebSocket arrive in Phase 2.
"""
from fastapi import APIRouter, Depends, Query

from webapp import stores
from webapp.auth import require_token

router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])


@router.get("/status")
def status() -> dict:
    """Mode, Kite token freshness, market state, paper progress, go-live gate."""
    return stores.read_status()


@router.get("/positions")
def positions() -> dict:
    """Open positions + today's P&L / trade count (from the bot's state file)."""
    state = stores.read_state()
    return {
        "positions": state["positions"],
        "daily_pnl": state["daily_pnl"],
        "trades_today": state["trades_today"],
        "date": state.get("date"),
        "stale": state["stale"],
    }


@router.get("/trades")
def trades(source: str | None = Query(default=None, pattern="^(paper|live)$")) -> dict:
    rows = stores.read_trades(source=source)
    return {"count": len(rows), "trades": rows}


@router.get("/signals")
def signals(taken: bool | None = Query(default=None)) -> dict:
    rows = stores.read_signals(taken=taken)
    return {"count": len(rows), "signals": rows}


@router.get("/equity")
def equity(source: str | None = Query(default=None, pattern="^(paper|live)$")) -> dict:
    return stores.read_equity(source=source)
