"""
Candle cache — day-stamped CSV cache for backtest/sweep data.
Avoids refetching identical historical candles from Kite on every run.
Cache entries are keyed by symbol, interval and lookback days, and expire
automatically because the key includes today's date.
"""
import os
from datetime import datetime
from typing import Optional

import pandas as pd

from src.logger import get_logger

logger = get_logger("candle_cache")


class CandleCache:
    def __init__(self, cache_dir: str = "data_cache"):
        self._dir = cache_dir

    def _path(self, symbol: str, interval: str, days: int) -> str:
        safe = symbol.replace(" ", "_").replace("&", "and").replace("-", "_")
        stamp = f"{datetime.now():%Y-%m-%d}"
        return os.path.join(self._dir, f"{safe}_{interval}_{days}d_{stamp}.csv")

    def get(self, symbol: str, interval: str, days: int) -> Optional[pd.DataFrame]:
        """Return cached candles for today's key, or None on miss."""
        path = self._path(symbol, interval, days)
        if not os.path.exists(path):
            return None
        try:
            df = pd.read_csv(path, parse_dates=["timestamp"])
            logger.info(f"Cache hit: {symbol} ({len(df)} candles)")
            return df
        except Exception as exc:
            logger.warning(f"Cache read failed for {symbol}: {exc}")
            return None

    def put(self, symbol: str, interval: str, days: int, df: pd.DataFrame) -> None:
        try:
            os.makedirs(self._dir, exist_ok=True)
            df.to_csv(self._path(symbol, interval, days), index=False)
        except OSError as exc:
            logger.warning(f"Cache write failed for {symbol}: {exc}")

    def get_or_fetch(self, symbol: str, interval: str, days: int, fetch_fn):
        """Cache-through helper: fetch_fn() is called only on a miss."""
        df = self.get(symbol, interval, days)
        if df is not None:
            return df
        df = fetch_fn()
        if df is not None and not df.empty:
            self.put(symbol, interval, days, df)
        return df
