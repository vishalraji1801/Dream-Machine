"""
Event calendar — deterministic 'avoid volatile periods' filter (SCRUM-82).

Blocks entries on market-wide event days (RBI policy, budget, F&O expiry) and on
a stock's own event days (earnings, corporate actions). This is the code-enforced
core of the plan's "look at volatile periods and avoid them"; the scheduled Claude
agent maintains the dates weekly in config/events.yaml.
"""
import os
from datetime import date, datetime
from typing import Optional

import yaml

from src.logger import get_logger

logger = get_logger("event_calendar")


class EventCalendar:
    def __init__(self, cfg: dict):
        ev = cfg.get("events", {})
        self._path = ev.get("path", "config/events.yaml")
        self._market_days: set[str] = set()
        self._earnings: dict[str, set[str]] = {}
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path) as f:
                data = yaml.safe_load(f) or {}
        except (OSError, yaml.YAMLError) as exc:
            logger.error(f"event calendar unreadable ({exc}) — no events loaded")
            return
        self._market_days = {str(d) for d in (data.get("market_event_days") or [])}
        self._earnings = {
            sym: {str(d) for d in dates}
            for sym, dates in (data.get("earnings") or {}).items()
        }
        logger.info(f"Event calendar: {len(self._market_days)} market days, "
                    f"{len(self._earnings)} symbols with events")

    def is_market_event_day(self, d: Optional[date] = None) -> bool:
        d = d or datetime.now().date()
        return d.isoformat() in self._market_days

    def symbol_has_event(self, symbol: str, d: Optional[date] = None) -> bool:
        d = d or datetime.now().date()
        return d.isoformat() in self._earnings.get(symbol, set())
