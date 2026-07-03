"""
Position manager.
Tracks open positions, monitors stop-loss and target levels, and handles EOD square-off.
"""
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Optional

from src.logger import get_logger

logger = get_logger("position_manager")


@dataclass
class Position:
    symbol: str
    direction: str          # "BUY" or "SELL"
    entry_price: float
    quantity: int
    stop_loss: float
    target: float
    entry_time: datetime = field(default_factory=datetime.now)
    trailing_sl_active: bool = False
    gtt_id: Optional[int] = None  # Kite GTT trigger ID (set after entry fills)

    def unrealized_pnl(self, current_price: float) -> float:
        if self.direction == "BUY":
            return (current_price - self.entry_price) * self.quantity
        return (self.entry_price - current_price) * self.quantity


class PositionManager:
    def __init__(self, cfg: dict):
        self._r = cfg["risk"]
        self._t = cfg["trading"]
        self._positions: dict[str, Position] = {}

    # ── CRUD ─────────────────────────────────────────────────────────────────

    def add_position(
        self, symbol: str, direction: str, entry_price: float,
        quantity: int, stop_loss: float, target: float
    ) -> None:
        self._positions[symbol] = Position(symbol, direction, entry_price, quantity, stop_loss, target)
        logger.info(f"Opened: {direction} {symbol} qty={quantity} entry={entry_price} sl={stop_loss} tgt={target}")

    def remove_position(self, symbol: str) -> Position | None:
        pos = self._positions.pop(symbol, None)
        if pos:
            logger.info(f"Closed position: {symbol}")
        return pos

    def restore(self, positions: list[Position]) -> None:
        """Re-adopt positions from a saved state file (crash recovery)."""
        for pos in positions:
            self._positions[pos.symbol] = pos
            logger.warning(f"Restored position: {pos.direction} {pos.symbol} "
                           f"qty={pos.quantity} entry={pos.entry_price} sl={pos.stop_loss}")

    def get_open_positions(self) -> list[Position]:
        return list(self._positions.values())

    def open_count(self) -> int:
        return len(self._positions)

    def set_gtt_id(self, symbol: str, gtt_id: int) -> None:
        """Store the Kite GTT trigger ID on the open position."""
        pos = self._positions.get(symbol)
        if pos:
            pos.gtt_id = gtt_id
            logger.info(f"{symbol}: GTT OCO registered, gtt_id={gtt_id}")

    # ── Exit checks ───────────────────────────────────────────────────────────

    def check_exit(self, symbol: str, current_price: float) -> tuple[bool, str]:
        """Returns (should_exit, reason) based on SL / target levels only."""
        pos = self._positions.get(symbol)
        if not pos:
            return False, ""

        if pos.direction == "BUY":
            if current_price <= pos.stop_loss:
                pnl = (pos.stop_loss - pos.entry_price) * pos.quantity
                logger.warning(f"{symbol}: SL hit | price={current_price} sl={pos.stop_loss} pnl=Rs.{pnl:.2f}")
                return True, "sl_hit"
            if current_price >= pos.target:
                pnl = (pos.target - pos.entry_price) * pos.quantity
                logger.info(f"{symbol}: Target hit | price={current_price} tgt={pos.target} pnl=Rs.{pnl:.2f}")
                return True, "target_hit"
        else:
            if current_price >= pos.stop_loss:
                pnl = (pos.entry_price - pos.stop_loss) * pos.quantity
                logger.warning(f"{symbol}: SL hit (SELL) | price={current_price} sl={pos.stop_loss} pnl=Rs.{pnl:.2f}")
                return True, "sl_hit"
            if current_price <= pos.target:
                pnl = (pos.entry_price - pos.target) * pos.quantity
                logger.info(f"{symbol}: Target hit (SELL) | price={current_price} tgt={pos.target} pnl=Rs.{pnl:.2f}")
                return True, "target_hit"

        return False, ""

    # ── Trailing SL ───────────────────────────────────────────────────────────

    def update_trailing_sl(self, symbol: str, current_price: float) -> float | None:
        """Advance trailing SL if profit activation threshold is met. Returns new SL or None."""
        pos = self._positions.get(symbol)
        if not pos or not self._r["trailing_sl_enabled"]:
            return None

        act_pct = self._r["trailing_sl_activation_pct"] / 100
        step_pct = self._r["trailing_sl_step_pct"] / 100

        if pos.direction == "BUY":
            profit_pct = (current_price - pos.entry_price) / pos.entry_price
            if profit_pct < act_pct:
                return None
            steps = int((profit_pct - act_pct) / step_pct)
            new_sl = round(pos.entry_price * (1 + steps * step_pct), 2)
            new_sl = max(new_sl, pos.entry_price)
        else:
            profit_pct = (pos.entry_price - current_price) / pos.entry_price
            if profit_pct < act_pct:
                return None
            steps = int((profit_pct - act_pct) / step_pct)
            new_sl = round(pos.entry_price * (1 - steps * step_pct), 2)
            new_sl = min(new_sl, pos.entry_price)

        if new_sl != pos.stop_loss:
            logger.info(f"{symbol}: trailing SL {pos.stop_loss} → {new_sl}")
            pos.stop_loss = new_sl
            pos.trailing_sl_active = True
            return new_sl
        return None

    # ── EOD square-off ────────────────────────────────────────────────────────

    def is_square_off_time(self) -> bool:
        sq = time(*map(int, self._t["square_off_time"].split(":")))
        return datetime.now().time() >= sq

    def get_positions_for_square_off(self) -> list[Position]:
        """Return all open positions once square-off time has been reached."""
        if not self.is_square_off_time():
            return []
        positions = list(self._positions.values())
        if positions:
            logger.warning(f"EOD square-off triggered: {len(positions)} positions to close")
        return positions

    def verify_all_closed(self) -> bool:
        """Called after square-off. Returns True if no open positions remain."""
        if self._positions:
            logger.critical(f"Square-off incomplete: {list(self._positions.keys())} still open!")
            return False
        logger.info("All positions confirmed closed after square-off")
        return True
