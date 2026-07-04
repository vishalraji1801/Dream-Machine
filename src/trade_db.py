"""
SQLite ledger (trades.db) — the unified data store for the AI strategist.

One database, four tables, every row tagged with a `source` (live / paper /
backtest) so a single query can compare all three. This is what the scheduled
Claude agents read; it replaces scattered CSVs for analysis purposes (the
per-day CSV ledger in trade_ledger.py is kept for human-readable journals).
"""
import os
import sqlite3
import threading
from datetime import datetime
from typing import Optional

from src.logger import get_logger

logger = get_logger("trade_db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT NOT NULL,          -- live | paper | backtest
    strategy     TEXT,
    symbol       TEXT NOT NULL,
    direction    TEXT NOT NULL,
    quantity     INTEGER NOT NULL,
    entry_price  REAL NOT NULL,
    exit_price   REAL NOT NULL,
    entry_time   TEXT NOT NULL,
    exit_time    TEXT NOT NULL,
    pnl          REAL NOT NULL,
    costs        REAL DEFAULT 0,
    exit_reason  TEXT,
    recorded_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS signals (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT NOT NULL,
    ts           TEXT NOT NULL,
    symbol       TEXT NOT NULL,
    direction    TEXT NOT NULL,
    strategy     TEXT,
    taken        INTEGER NOT NULL,       -- 1 acted on, 0 skipped
    reason       TEXT                    -- why skipped (regime, spread, risk...)
);
CREATE TABLE IF NOT EXISTS scanner_rankings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT NOT NULL,
    symbol       TEXT NOT NULL,
    rank         INTEGER,
    score        REAL,
    rvol         REAL,
    pct_change   REAL
);
CREATE TABLE IF NOT EXISTS cycle_snapshots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT NOT NULL,
    open_positions INTEGER,
    daily_pnl     REAL,
    trades_today  INTEGER,
    regime        TEXT
);
"""


class TradeDB:
    def __init__(self, path: str = os.path.join("logs", "trades.db")):
        self._path = path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with self._connect() as con:
            con.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self._path, timeout=10)
        con.row_factory = sqlite3.Row
        return con

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat(timespec="seconds")

    # ── Writes ──────────────────────────────────────────────────────────────────

    def record_trade(self, *, source: str, symbol: str, direction: str, quantity: int,
                     entry_price: float, exit_price: float, entry_time, exit_time,
                     pnl: float, costs: float = 0.0, exit_reason: str = "",
                     strategy: Optional[str] = None) -> None:
        row = (source, strategy, symbol, direction, quantity,
               round(entry_price, 2), round(exit_price, 2),
               self._as_iso(entry_time), self._as_iso(exit_time),
               round(pnl, 2), round(costs, 2), exit_reason, self._now())
        self._exec(
            "INSERT INTO trades (source, strategy, symbol, direction, quantity, "
            "entry_price, exit_price, entry_time, exit_time, pnl, costs, exit_reason, recorded_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", row)

    def record_signal(self, *, source: str, symbol: str, direction: str, taken: bool,
                      reason: str = "", strategy: Optional[str] = None, ts=None) -> None:
        self._exec(
            "INSERT INTO signals (source, ts, symbol, direction, strategy, taken, reason) "
            "VALUES (?,?,?,?,?,?,?)",
            (source, self._as_iso(ts or datetime.now()), symbol, direction,
             strategy, 1 if taken else 0, reason))

    def record_scan(self, rankings: list[dict], ts=None) -> None:
        stamp = self._as_iso(ts or datetime.now())
        rows = [(stamp, r.get("symbol"), r.get("rank"), r.get("score"),
                 r.get("rvol"), r.get("pct_change")) for r in rankings]
        self._exec_many(
            "INSERT INTO scanner_rankings (ts, symbol, rank, score, rvol, pct_change) "
            "VALUES (?,?,?,?,?,?)", rows)

    def record_snapshot(self, *, open_positions: int, daily_pnl: float,
                        trades_today: int, regime: Optional[str] = None, ts=None) -> None:
        self._exec(
            "INSERT INTO cycle_snapshots (ts, open_positions, daily_pnl, trades_today, regime) "
            "VALUES (?,?,?,?,?)",
            (self._as_iso(ts or datetime.now()), open_positions,
             round(daily_pnl, 2), trades_today, regime))

    # ── Reads (used by tests and AI agents) ─────────────────────────────────────

    def trades(self, source: Optional[str] = None) -> list[dict]:
        q = "SELECT * FROM trades"
        args: tuple = ()
        if source:
            q += " WHERE source = ?"
            args = (source,)
        with self._lock, self._connect() as con:
            return [dict(r) for r in con.execute(q + " ORDER BY id", args)]

    def signals(self, taken: Optional[bool] = None) -> list[dict]:
        q = "SELECT * FROM signals"
        args: tuple = ()
        if taken is not None:
            q += " WHERE taken = ?"
            args = (1 if taken else 0,)
        with self._lock, self._connect() as con:
            return [dict(r) for r in con.execute(q + " ORDER BY id", args)]

    # ── Internals ───────────────────────────────────────────────────────────────

    @staticmethod
    def _as_iso(value) -> str:
        if isinstance(value, datetime):
            return value.isoformat(timespec="seconds")
        return str(value)

    def _exec(self, sql: str, params: tuple) -> None:
        try:
            with self._lock, self._connect() as con:
                con.execute(sql, params)
                con.commit()
        except sqlite3.Error as exc:
            logger.error(f"trade_db write failed: {exc}")

    def _exec_many(self, sql: str, rows: list[tuple]) -> None:
        if not rows:
            return
        try:
            with self._lock, self._connect() as con:
                con.executemany(sql, rows)
                con.commit()
        except sqlite3.Error as exc:
            logger.error(f"trade_db bulk write failed: {exc}")
