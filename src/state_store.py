"""
State store — crash recovery.
Persists open positions and daily risk counters to disk after every cycle,
so a crashed bot can restart mid-day without losing track of its positions,
P&L, or circuit-breaker state.
"""
import json
import os
from datetime import datetime
from typing import Optional

from src.logger import get_logger
from src.position_manager import Position

logger = get_logger("state_store")


class StateStore:
    def __init__(self, path: str = os.path.join("logs", "bot_state.json")):
        self._path = path

    def save(self, daily_pnl: float, trades_today: int, positions: list[Position]) -> None:
        """Write the current bot state to disk (atomic replace)."""
        state = {
            "date": f"{datetime.now():%Y-%m-%d}",
            "daily_pnl": daily_pnl,
            "trades_today": trades_today,
            "positions": [
                {
                    "symbol": p.symbol,
                    "direction": p.direction,
                    "entry_price": p.entry_price,
                    "quantity": p.quantity,
                    "stop_loss": p.stop_loss,
                    "target": p.target,
                    "entry_time": p.entry_time.isoformat(),
                    "trailing_sl_active": p.trailing_sl_active,
                    "gtt_id": p.gtt_id,
                }
                for p in positions
            ],
        }
        try:
            os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
            tmp = self._path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(state, f, indent=2)
            os.replace(tmp, self._path)
        except OSError as exc:
            logger.error(f"Failed to save state: {exc}")

    def load(self) -> Optional[dict]:
        """
        Return saved state if it is from today, else None.
        Positions are deserialized back into Position objects.
        """
        if not os.path.exists(self._path):
            return None
        try:
            with open(self._path) as f:
                state = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.error(f"Failed to load state: {exc}")
            return None

        if state.get("date") != f"{datetime.now():%Y-%m-%d}":
            logger.info("Saved state is from a previous day — ignoring")
            return None

        try:
            state["positions"] = [
                Position(
                    symbol=p["symbol"], direction=p["direction"],
                    entry_price=p["entry_price"], quantity=p["quantity"],
                    stop_loss=p["stop_loss"], target=p["target"],
                    entry_time=datetime.fromisoformat(p["entry_time"]),
                    trailing_sl_active=p["trailing_sl_active"],
                    gtt_id=p["gtt_id"],
                )
                for p in state.get("positions", [])
            ]
        except (KeyError, ValueError) as exc:
            logger.error(f"Corrupt position data in state file: {exc}")
            return None

        logger.warning(
            f"Restoring same-day state: {len(state['positions'])} positions, "
            f"P&L Rs.{state['daily_pnl']:.2f}, {state['trades_today']} trades"
        )
        return state

    def clear(self) -> None:
        """Delete the state file (called after a clean EOD square-off)."""
        try:
            if os.path.exists(self._path):
                os.remove(self._path)
                logger.info("State file cleared")
        except OSError as exc:
            logger.error(f"Failed to clear state: {exc}")
