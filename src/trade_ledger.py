"""
Trade ledger.
Appends every closed trade to a daily CSV (logs/trades_YYYY-MM-DD.csv)
and builds the per-trade EOD breakdown sent to Telegram.
"""
import csv
import os
from datetime import datetime
from typing import Optional

from src.logger import get_logger

logger = get_logger("trade_ledger")

_COLUMNS = [
    "symbol", "direction", "quantity", "entry_price", "exit_price",
    "entry_time", "exit_time", "pnl", "exit_reason",
]


class TradeLedger:
    def __init__(self, log_dir: str = "logs"):
        self._log_dir = log_dir

    def _path(self, day: Optional[datetime] = None) -> str:
        day = day or datetime.now()
        return os.path.join(self._log_dir, f"trades_{day:%Y-%m-%d}.csv")

    def record(
        self,
        symbol: str,
        direction: str,
        quantity: int,
        entry_price: float,
        exit_price: float,
        entry_time: datetime,
        exit_time: datetime,
        pnl: float,
        exit_reason: str,
    ) -> None:
        """Append one closed trade to today's CSV, creating it with a header if new."""
        os.makedirs(self._log_dir, exist_ok=True)
        path = self._path()
        is_new = not os.path.exists(path)
        try:
            with open(path, "a", newline="") as f:
                writer = csv.writer(f)
                if is_new:
                    writer.writerow(_COLUMNS)
                writer.writerow([
                    symbol, direction, quantity,
                    round(entry_price, 2), round(exit_price, 2),
                    f"{entry_time:%Y-%m-%d %H:%M:%S}", f"{exit_time:%Y-%m-%d %H:%M:%S}",
                    round(pnl, 2), exit_reason,
                ])
            logger.info(f"Trade recorded: {direction} {quantity}x{symbol} pnl={pnl:.2f} ({exit_reason})")
        except OSError as exc:
            logger.error(f"Failed to write trade ledger: {exc}")

    def today_trades(self) -> list[dict]:
        """Return today's trades as a list of dicts (empty if no file)."""
        path = self._path()
        if not os.path.exists(path):
            return []
        try:
            with open(path, newline="") as f:
                return list(csv.DictReader(f))
        except OSError as exc:
            logger.error(f"Failed to read trade ledger: {exc}")
            return []

    def format_summary(self) -> Optional[str]:
        """Per-trade EOD breakdown for Telegram. None if no trades today."""
        trades = self.today_trades()
        if not trades:
            return None
        lines = ["Today's trades:"]
        for t in trades:
            pnl = float(t["pnl"])
            sign = "+" if pnl >= 0 else ""
            lines.append(
                f"{t['direction']} {t['quantity']}x{t['symbol']} | "
                f"{t['entry_price']} -> {t['exit_price']} | "
                f"{sign}{pnl:.2f} | {t['exit_reason']}"
            )
        return "\n".join(lines)
