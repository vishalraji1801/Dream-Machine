"""Phase 5 — backtest job engine (fake store, real config, polled to completion)."""
import os
import time

import pandas as pd
import pytest

from webapp.backtest_jobs import BacktestJobs

CONFIG = os.path.join("config", "config.yaml")


def _candles(sessions=8):
    """Realistic 15-min sessions (09:15–15:15) across business days. Low flat
    price so risk-based sizing stays under the ₹120k order_value_cap."""
    rows = []
    day = pd.Timestamp("2026-06-01")
    made = 0
    while made < sessions:
        if day.weekday() < 5:
            bars = pd.date_range(f"{day.date()} 09:15", f"{day.date()} 15:15", freq="15min")
            for ts in bars:
                rows.append((ts, 100.0, 103.0, 97.0, 100.0, 500_000))
            made += 1
        day += pd.Timedelta(days=1)
    return pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])


class FakeStore:
    def __init__(self):
        self._df = _candles()

    def symbols(self, tf):
        return ["ACME", "BETA"] if tf == "15min" else []

    def get_candles(self, sym, tf):
        return self._df.copy()


def _wait(jobs, job_id, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        job = jobs.get(job_id)
        if job and job["status"] != "running":
            return job
        time.sleep(0.02)
    raise AssertionError("job did not finish in time")


@pytest.fixture
def jobs():
    return BacktestJobs(CONFIG, store=FakeStore())


def test_data_summary_lists_timeframes(jobs):
    s = jobs.data_summary()
    assert "15min" in s["timeframes"]
    assert s["timeframes"]["15min"]["symbols"] == 2


def test_job_runs_to_completion(jobs):
    job_id = jobs.submit(strategy="", timeframe="15min", window=60)
    job = _wait(jobs, job_id)
    assert job["status"] == "done"
    agg = job["result"]["aggregate"]
    assert agg["symbols_tested"] == 2
    # empty registry -> no strategy -> no trades, but the pipeline completes
    assert agg["total_trades"] == 0
    assert set(agg) >= {"net_pnl", "win_rate", "profit_factor", "total_trades"}


def test_submit_unknown_timeframe_raises(jobs):
    with pytest.raises(ValueError, match="no stored candles"):
        jobs.submit(strategy="", timeframe="4hr")


def test_registered_strategy_produces_trades(jobs, monkeypatch):
    # register a trivial always-enter strategy so the engine actually trades
    from src import strategy as strat

    def always_buy(symbol, df, cfg):
        entry = float(df["close"].iloc[-1])
        return strat.TradeSignal("BUY", symbol, entry, entry - 10, entry + 20, "always_buy")

    monkeypatch.setitem(strat.STRATEGY_REGISTRY, "always_buy", always_buy)
    job_id = jobs.submit(strategy="always_buy", timeframe="15min", window=30,
                         overrides={"regime_filter_enabled": False})
    job = _wait(jobs, job_id)
    assert job["status"] == "done"
    assert job["result"]["aggregate"]["total_trades"] > 0
