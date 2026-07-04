"""
Backtest candle store (SCRUM-93).

A dedicated SQLite database for backtesting — separate from the live trades.db.
Holds up to a year of OHLCV candles per (symbol, timeframe), so the multi-
timeframe backtest pipeline reads from disk instead of hammering the Kite
historical API on every run.

Rows are unique on (symbol, timeframe, timestamp) so re-loading is idempotent:
an overlapping fetch updates existing bars rather than duplicating them. A small
fetch_log records when each (symbol, timeframe) was last pulled, enabling
"already fetched today → skip" freshness checks.
"""
import os
import sqlite3
from datetime import datetime
from typing import Optional

import pandas as pd

from src.logger import get_logger

logger = get_logger("backtest_store")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS candles (
    symbol     TEXT NOT NULL,
    timeframe  TEXT NOT NULL,
    timestamp  TEXT NOT NULL,
    open       REAL, high REAL, low REAL, close REAL, volume REAL,
    PRIMARY KEY (symbol, timeframe, timestamp)
);
CREATE TABLE IF NOT EXISTS fetch_log (
    symbol      TEXT NOT NULL,
    timeframe   TEXT NOT NULL,
    fetched_on  TEXT NOT NULL,   -- YYYY-MM-DD
    rows        INTEGER,
    PRIMARY KEY (symbol, timeframe)
);
"""


class BacktestStore:
    def __init__(self, path: str = os.path.join("data_cache", "backtest_data.db")):
        self._path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with self._connect() as con:
            con.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self._path, timeout=30)
        con.row_factory = sqlite3.Row
        return con

    # ── writes ──────────────────────────────────────────────────────────────────

    def upsert_candles(self, symbol: str, timeframe: str, df: pd.DataFrame) -> int:
        """Insert/replace candles for (symbol, timeframe). Returns rows written."""
        if df is None or df.empty:
            return 0
        rows = [
            (symbol, timeframe, str(r["timestamp"]),
             float(r["open"]), float(r["high"]), float(r["low"]),
             float(r["close"]), float(r["volume"]))
            for _, r in df.iterrows()
        ]
        with self._connect() as con:
            con.executemany(
                "INSERT OR REPLACE INTO candles "
                "(symbol, timeframe, timestamp, open, high, low, close, volume) "
                "VALUES (?,?,?,?,?,?,?,?)", rows)
            con.execute(
                "INSERT OR REPLACE INTO fetch_log (symbol, timeframe, fetched_on, rows) "
                "VALUES (?,?,?,?)",
                (symbol, timeframe, f"{datetime.now():%Y-%m-%d}",
                 self._count(con, symbol, timeframe) + 0))
            con.commit()
        logger.info(f"Stored {len(rows)} {timeframe} candles for {symbol}")
        return len(rows)

    def clear(self) -> None:
        with self._connect() as con:
            con.execute("DELETE FROM candles")
            con.execute("DELETE FROM fetch_log")
            con.commit()
        logger.warning("Backtest store cleared")

    # ── reads ───────────────────────────────────────────────────────────────────

    def get_candles(self, symbol: str, timeframe: str) -> Optional[pd.DataFrame]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT timestamp, open, high, low, close, volume FROM candles "
                "WHERE symbol=? AND timeframe=? ORDER BY timestamp",
                (symbol, timeframe)).fetchall()
        if not rows:
            return None
        df = pd.DataFrame([dict(r) for r in rows])
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        return df

    def has_fresh(self, symbol: str, timeframe: str, day: Optional[str] = None) -> bool:
        """True if (symbol, timeframe) was fetched on `day` (default: today)."""
        day = day or f"{datetime.now():%Y-%m-%d}"
        with self._connect() as con:
            row = con.execute(
                "SELECT fetched_on FROM fetch_log WHERE symbol=? AND timeframe=?",
                (symbol, timeframe)).fetchone()
        return bool(row) and row["fetched_on"] == day

    def symbols(self, timeframe: Optional[str] = None) -> list[str]:
        q = "SELECT DISTINCT symbol FROM candles"
        args: tuple = ()
        if timeframe:
            q += " WHERE timeframe=?"
            args = (timeframe,)
        with self._connect() as con:
            return [r["symbol"] for r in con.execute(q + " ORDER BY symbol", args)]

    @staticmethod
    def _count(con, symbol: str, timeframe: str) -> int:
        return con.execute(
            "SELECT COUNT(*) FROM candles WHERE symbol=? AND timeframe=?",
            (symbol, timeframe)).fetchone()[0]

    def candle_count(self, symbol: str, timeframe: str) -> int:
        with self._connect() as con:
            return self._count(con, symbol, timeframe)
