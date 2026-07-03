"""
Market calendar — is the market open right now?
Combines weekday, the NSE holiday list from config, and market hours.
"""
from datetime import date, datetime, time
from typing import Optional

from src.logger import get_logger

logger = get_logger("market_calendar")


class MarketCalendar:
    def __init__(self, cfg: dict):
        t = cfg["trading"]
        self._holidays = {
            date.fromisoformat(str(h)) for h in t.get("holidays", [])
        }
        self._open = time(*map(int, t["market_open"].split(":")))
        self._close = time(*map(int, t["market_close"].split(":")))

    def is_trading_day(self, d: Optional[date] = None) -> bool:
        """Weekday and not an NSE holiday."""
        d = d or datetime.now().date()
        if d.weekday() >= 5:  # Saturday=5, Sunday=6
            return False
        return d not in self._holidays

    def is_market_open_now(self, now: Optional[datetime] = None) -> bool:
        """Trading day and within market hours."""
        now = now or datetime.now()
        if not self.is_trading_day(now.date()):
            return False
        return self._open <= now.time() <= self._close

    def status_text(self) -> str:
        if not self.is_trading_day():
            return "CLOSED (holiday/weekend)"
        return "OPEN" if self.is_market_open_now() else "CLOSED (outside hours)"
