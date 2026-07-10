"""
Backtest jobs — run the existing Backtester over stored candles off the request
thread, so a year of data doesn't block the API. Jobs are in-memory (a personal,
single-user tool); results are returned by polling.

Each job loads the saved config, applies the requested strategy + overrides, runs
every stored symbol for the timeframe, and aggregates one BacktestResult.
"""
import copy
import threading
import uuid
from typing import Any, Optional

import yaml

from src.backtest_store import BacktestStore
from src.backtester import Backtester
from src.logger import get_logger

logger = get_logger("backtest_jobs")

_ALLOWED_OVERRIDES = {
    "name", "sl_mode", "regime_filter_enabled", "ema_fast", "ema_slow",
    "rsi_period", "volume_multiplier", "atr_period", "atr_sl_mult",
    "atr_target_mult", "mtf_confirm",
}


def _build_cfg(config_path: str, strategy: str, overrides: dict) -> dict:
    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg = copy.deepcopy(cfg)
    cfg["strategy"]["name"] = strategy
    for k, v in (overrides or {}).items():
        if k in _ALLOWED_OVERRIDES:
            cfg["strategy"][k] = v
    return cfg


def _aggregate(per_symbol: list[dict]) -> dict:
    total = sum(s["total_trades"] for s in per_symbol)
    wins = sum(s["wins"] for s in per_symbol)
    net = round(sum(s["net_pnl"] for s in per_symbol), 2)
    gp = round(sum(s["gross_profit"] for s in per_symbol), 2)
    gl = round(sum(s["gross_loss"] for s in per_symbol), 2)
    pf = round(gp / gl, 2) if gl > 0 else (float("inf") if gp > 0 else 0.0)
    return {
        "total_trades": total,
        "wins": wins,
        "losses": total - wins,
        "win_rate": round(100 * wins / total, 2) if total else 0.0,
        "net_pnl": net,
        "profit_factor": pf if pf != float("inf") else None,
        "gross_profit": gp,
        "gross_loss": gl,
        "symbols_tested": len(per_symbol),
    }


def _result_row(symbol: str, r) -> dict:
    return {
        "symbol": symbol,
        "total_trades": r.total_trades,
        "wins": r.wins,
        "net_pnl": r.net_pnl,
        "gross_profit": r.gross_profit,
        "gross_loss": r.gross_loss,
        "win_rate": r.win_rate,
        "profit_factor": r.profit_factor if r.profit_factor != float("inf") else None,
        "max_drawdown": r.max_drawdown,
    }


class BacktestJobs:
    def __init__(self, config_path: str, store: Optional[BacktestStore] = None):
        self._config_path = config_path
        self._store = store or BacktestStore()
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def data_summary(self) -> dict:
        """Available timeframes and symbol/candle counts in the store."""
        tfs: dict[str, Any] = {}
        for tf in ("1min", "5min", "15min", "30min", "1hr"):
            syms = self._store.symbols(tf)
            if syms:
                tfs[tf] = {"symbols": len(syms), "sample": syms[:8]}
        return {"timeframes": tfs}

    def submit(self, strategy: str, timeframe: str, window: int = 60,
               overrides: Optional[dict] = None,
               symbols: Optional[list[str]] = None) -> str:
        available = self._store.symbols(timeframe)
        if not available:
            raise ValueError(f"no stored candles for timeframe {timeframe!r}")
        chosen = [s for s in (symbols or available) if s in available] or available
        job_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._jobs[job_id] = {"status": "running", "result": None, "error": None,
                                  "strategy": strategy, "timeframe": timeframe}
        t = threading.Thread(target=self._run, name=f"bt-{job_id}",
                             args=(job_id, strategy, timeframe, window, overrides or {}, chosen),
                             daemon=True)
        t.start()
        return job_id

    def get(self, job_id: str) -> Optional[dict]:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def _run(self, job_id: str, strategy: str, timeframe: str, window: int,
             overrides: dict, symbols: list[str]) -> None:
        try:
            cfg = _build_cfg(self._config_path, strategy, overrides)
            bt = Backtester(cfg, window=window)
            rows = []
            for sym in symbols:
                df = self._store.get_candles(sym, timeframe)
                if df is None or df.empty:
                    continue
                r = bt.run({sym: df})
                rows.append(_result_row(sym, r))
            result = {"aggregate": _aggregate(rows), "per_symbol": rows}
            with self._lock:
                self._jobs[job_id].update(status="done", result=result)
            logger.info(f"backtest {job_id} done: {result['aggregate']['total_trades']} trades")
        except Exception as exc:  # surface to the UI, don't crash the server
            logger.error(f"backtest {job_id} failed: {exc}", exc_info=True)
            with self._lock:
                self._jobs[job_id].update(status="error", error=str(exc))


_jobs: Optional[BacktestJobs] = None


def get_jobs(config_path: str) -> BacktestJobs:
    global _jobs
    if _jobs is None:
        _jobs = BacktestJobs(config_path)
    return _jobs
