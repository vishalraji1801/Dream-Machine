"""
Read layer — thin accessors over the state the bot already persists.

Everything here is read-only and safe to call whether or not the bot process is
running. Live position/P&L come from logs/bot_state.json (written every cycle by
StateStore); trades, signals and the P&L curve come from logs/trades.db.
"""
import json
import os
from datetime import datetime

from src.ops import gather_status
from src.trade_db import TradeDB
from webapp.settings import get_settings


def read_status() -> dict:
    """Mode, token freshness, market state, paper progress + go-live gate."""
    return gather_status(get_settings().config_path)


def read_state() -> dict:
    """
    Raw same-cycle bot state (positions, daily P&L, trades today). Read directly
    from JSON so we get a snapshot regardless of day and without needing the bot
    process. `stale` is True when the file is from a previous day (bot not run
    today) or missing.
    """
    path = get_settings().state_path
    today = f"{datetime.now():%Y-%m-%d}"
    if not os.path.exists(path):
        return {"positions": [], "daily_pnl": 0.0, "trades_today": 0,
                "date": None, "stale": True}
    try:
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"positions": [], "daily_pnl": 0.0, "trades_today": 0,
                "date": None, "stale": True}
    state.setdefault("positions", [])
    state.setdefault("daily_pnl", 0.0)
    state.setdefault("trades_today", 0)
    state["stale"] = state.get("date") != today
    return state


def read_trades(source: str | None = None) -> list[dict]:
    return TradeDB().trades(source=source)


def read_signals(taken: bool | None = None) -> list[dict]:
    return TradeDB().signals(taken=taken)


def read_equity(source: str | None = None) -> dict:
    """
    Build the P&L curve. Preferred source is cycle_snapshots (intraday daily_pnl
    over time). Also returns a per-trade cumulative curve as a fallback/summary.
    """
    db = TradeDB()
    snaps = db.snapshots()
    trades = db.trades(source=source)

    cum, running = [], 0.0
    for t in trades:
        running += float(t.get("pnl") or 0.0)
        cum.append({"exit_time": t.get("exit_time"), "symbol": t.get("symbol"),
                    "pnl": round(float(t.get("pnl") or 0.0), 2),
                    "cumulative": round(running, 2)})

    return {
        "snapshots": [
            {"ts": s.get("ts"), "daily_pnl": s.get("daily_pnl"),
             "open_positions": s.get("open_positions"),
             "trades_today": s.get("trades_today"), "regime": s.get("regime")}
            for s in snaps
        ],
        "trade_curve": cum,
        "net_pnl": round(running, 2),
        "trade_count": len(trades),
    }
