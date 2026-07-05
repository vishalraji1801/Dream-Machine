"""
Chunked historical loader (SCRUM-94).

Kite caps the span of a single historical request per interval (1-min: 60 days,
5-min: 100, 15/30-min: 200, 60-min: 400). To pull a full year we split the
window into per-interval chunks, fetch each with retry, concatenate, dedup, and
store into the backtest DB. Symbols already fetched today are skipped.
"""
import time
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

from src.logger import get_logger

logger = get_logger("historical_loader")

# Default timeframe map if config omits it. label -> (kite interval, max days/request)
DEFAULT_TIMEFRAMES = [
    {"label": "1min",  "interval": "minute",   "max_days": 60},
    {"label": "5min",  "interval": "5minute",  "max_days": 100},
    {"label": "15min", "interval": "15minute", "max_days": 200},
    {"label": "30min", "interval": "30minute", "max_days": 200},
    {"label": "1hr",   "interval": "60minute", "max_days": 400},
]


def chunk_ranges(end: datetime, lookback_days: int, max_days: int) -> list:
    """Contiguous (from, to) datetime windows covering `lookback_days` back from
    `end`, each spanning at most `max_days`. Oldest first."""
    start = end - timedelta(days=lookback_days)
    windows = []
    cur = start
    while cur < end:
        nxt = min(cur + timedelta(days=max_days), end)
        windows.append((cur, nxt))
        cur = nxt
    return windows


class HistoricalLoader:
    def __init__(self, kite, store, cfg: dict):
        bd = cfg.get("backtest_data", {})
        self._kite = kite
        self._store = store
        self._lookback = bd.get("lookback_days", 365)
        self._timeframes = bd.get("timeframes", DEFAULT_TIMEFRAMES)
        self._pause = bd.get("request_pause_sec", 0.34)  # ~3 req/s Kite limit

    @property
    def timeframes(self) -> list:
        return self._timeframes

    def load_symbol(self, symbol: str, token: int, end: Optional[datetime] = None,
                    force: bool = False) -> dict:
        """
        Ensure data up to `end` for every timeframe of one symbol, DELTA-loading:
        fetch only candles newer than what's already stored. Returns
        {timeframe_label: rows_stored} (0 = already current / skipped).
        force=True ignores existing data and refetches the full lookback.
        """
        end = end or datetime.now()
        result = {}
        for tf in self._timeframes:
            label = tf["label"]
            last = None if force else self._store.last_timestamp(symbol, label)
            if last is not None:
                if last.date() >= end.date():
                    result[label] = 0            # already current — no fetch
                    continue
                lookback = (end.date() - last.date()).days + 1   # delta window only
            else:
                lookback = self._lookback        # first load — full year
            df = self._fetch_timeframe(token, tf, end, lookback)
            result[label] = self._store.upsert_candles(symbol, label, df) if df is not None else 0
        return result

    def _fetch_timeframe(self, token: int, tf: dict, end: datetime,
                         lookback_days: Optional[int] = None) -> Optional[pd.DataFrame]:
        lookback_days = self._lookback if lookback_days is None else lookback_days
        frames = []
        for frm, to in chunk_ranges(end, lookback_days, tf["max_days"]):
            raw = self._with_retry(
                lambda t=token, a=frm, b=to, iv=tf["interval"]:
                self._kite.historical_data(t, a, b, iv))
            if raw:
                frames.append(pd.DataFrame(raw))
            if self._pause:
                time.sleep(self._pause)
        if not frames:
            return None
        df = pd.concat(frames, ignore_index=True)
        df.rename(columns={"date": "timestamp"}, inplace=True)
        df = (df[["timestamp", "open", "high", "low", "close", "volume"]]
              .drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True))
        return df

    def _with_retry(self, fn, retries: int = 3):
        for attempt in range(retries):
            try:
                return fn()
            except Exception as exc:
                logger.warning(f"historical fetch attempt {attempt + 1}/{retries} failed: {exc}")
                if attempt < retries - 1:
                    time.sleep(1 + attempt)
        logger.error("historical fetch exhausted retries — chunk skipped")
        return None
