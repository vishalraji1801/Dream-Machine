from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd

from src.backtest_runner import (format_summary, run_across_timeframes,
                                 select_stocks, _summarize)
from src.backtest_store import BacktestStore


def _df(n, base=100.0):
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-06-01 09:15", periods=n, freq="5min"),
        "open": [base] * n, "high": [base + 1] * n, "low": [base - 1] * n,
        "close": [base + 0.5] * n, "volume": [1000] * n,
    })


class _FakeBT:
    def __init__(self, cfg, window=60):
        pass

    def run(self, candles, index_candles=None):
        return SimpleNamespace(total_trades=5, net_pnl=1000.0, win_rate=52.0,
                               profit_factor=1.4, max_drawdown=300.0, trades=[])


def _cfg(labels):
    return {"backtest_data": {"timeframes": [{"label": l} for l in labels]},
            "strategy": {"name": "momentum_vwap_breakout"}}


def test_run_across_timeframes_one_summary_per_tf_with_data(tmp_path):
    store = BacktestStore(str(tmp_path / "bt.db"))
    store.upsert_candles("RELIANCE", "5min", _df(30))
    store.upsert_candles("RELIANCE", "1hr", _df(30))
    # 1min declared in config but has NO data -> should be skipped
    cfg = _cfg(["1min", "5min", "1hr"])
    summaries = run_across_timeframes(cfg, store, ["RELIANCE"], backtester_cls=_FakeBT)
    tfs = {s["timeframe"] for s in summaries}
    assert tfs == {"5min", "1hr"}
    assert all(s["trades"] == 5 for s in summaries)


def test_summarize_computes_expectancy_and_avg_cost():
    result = SimpleNamespace(
        total_trades=4, net_pnl=800.0, win_rate=50.0, profit_factor=1.3,
        max_drawdown=200.0,
        trades=[SimpleNamespace(costs=40.0) for _ in range(4)])
    s = _summarize("5min", {"A": _df(10), "B": _df(10)}, result)
    assert s["expectancy"] == 200.0        # 800 / 4
    assert s["est_costs"] == 160.0         # 4 x 40
    assert s["avg_cost"] == 40.0
    assert s["symbols"] == 2


def test_format_summary_lists_all_timeframes():
    summaries = [
        {"timeframe": "5min", "symbols": 30, "trades": 120, "net_pnl": 5000,
         "win_rate": 52.0, "profit_factor": 1.4, "max_drawdown": 3000,
         "expectancy": 41.6, "avg_cost": 40.0},
        {"timeframe": "1hr", "symbols": 30, "trades": 40, "net_pnl": 3200,
         "win_rate": 56.0, "profit_factor": 1.5, "max_drawdown": 2000,
         "expectancy": 80.0, "avg_cost": 30.0},
    ]
    text = format_summary(summaries, "momentum_vwap_breakout")
    assert "5min" in text and "1hr" in text
    assert "momentum_vwap_breakout" in text


def test_select_stocks_caps_at_num(tmp_path):
    kite = MagicMock()
    kite.instruments.return_value = [
        {"tradingsymbol": s, "instrument_token": i, "instrument_type": "EQ",
         "exchange": "NSE", "segment": "NSE"}
        for i, s in enumerate(["RELIANCE", "TCS", "INFY", "SBIN"], 1)
    ]
    kite.ltp.return_value = {f"NSE:{s}": {"last_price": 1000.0}
                            for s in ["RELIANCE", "TCS", "INFY", "SBIN"]}
    cfg = {"trading": {"exchange": "NSE"}, "universe": {}}
    stocks = select_stocks(kite, cfg, num_stocks=2)
    assert len(stocks) == 2
    assert all("symbol" in s and "token" in s for s in stocks)
