from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pandas as pd

from src.backtest_store import BacktestStore
from src.historical_loader import HistoricalLoader, chunk_ranges


# ── chunk_ranges ──────────────────────────────────────────────────────────────

def test_chunk_ranges_one_year_1min():
    end = datetime(2026, 7, 6)
    windows = chunk_ranges(end, lookback_days=365, max_days=60)
    assert len(windows) == 7                       # ceil(365/60)
    assert windows[0][0] == end - timedelta(days=365)
    assert windows[-1][1] == end                   # last window ends at end
    for frm, to in windows:
        assert (to - frm).days <= 60               # respects per-request cap


def test_chunk_ranges_one_year_1hr_single_window():
    end = datetime(2026, 7, 6)
    windows = chunk_ranges(end, lookback_days=365, max_days=400)
    assert len(windows) == 1
    assert windows[0] == (end - timedelta(days=365), end)


def test_chunk_ranges_contiguous():
    end = datetime(2026, 7, 6)
    windows = chunk_ranges(end, lookback_days=200, max_days=100)
    assert len(windows) == 2
    assert windows[0][1] == windows[1][0]          # no gaps/overlap


# ── HistoricalLoader ──────────────────────────────────────────────────────────

def _cfg(tmp_path):
    return {"backtest_data": {
        "lookback_days": 120, "request_pause_sec": 0,
        "timeframes": [{"label": "5min", "interval": "5minute", "max_days": 100}],
    }}


def _canned_rows():
    return [
        {"date": pd.Timestamp("2026-06-01 09:15"), "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 100},
        {"date": pd.Timestamp("2026-06-01 09:20"), "open": 1.5, "high": 2.5, "low": 1, "close": 2, "volume": 120},
        {"date": pd.Timestamp("2026-06-01 09:25"), "open": 2, "high": 2.2, "low": 1.8, "close": 2.1, "volume": 90},
    ]


def test_load_symbol_stores_deduped_candles(tmp_path):
    store = BacktestStore(str(tmp_path / "bt.db"))
    kite = MagicMock()
    kite.historical_data.return_value = _canned_rows()   # same rows each chunk
    loader = HistoricalLoader(kite, store, _cfg(tmp_path))
    res = loader.load_symbol("RELIANCE", 738561)
    assert res["5min"] == 3                                # 2 chunks, deduped to 3
    assert store.candle_count("RELIANCE", "5min") == 3
    assert kite.historical_data.call_count == 2            # 120d / 100d = 2 chunks


def test_load_symbol_skips_when_fresh(tmp_path):
    store = BacktestStore(str(tmp_path / "bt.db"))
    kite = MagicMock()
    kite.historical_data.return_value = _canned_rows()
    loader = HistoricalLoader(kite, store, _cfg(tmp_path))
    loader.load_symbol("RELIANCE", 738561)
    kite.historical_data.reset_mock()
    res = loader.load_symbol("RELIANCE", 738561)           # already fresh today
    assert res["5min"] == 0
    kite.historical_data.assert_not_called()


def test_load_symbol_force_refetches(tmp_path):
    store = BacktestStore(str(tmp_path / "bt.db"))
    kite = MagicMock()
    kite.historical_data.return_value = _canned_rows()
    loader = HistoricalLoader(kite, store, _cfg(tmp_path))
    loader.load_symbol("RELIANCE", 738561)
    kite.historical_data.reset_mock()
    loader.load_symbol("RELIANCE", 738561, force=True)
    assert kite.historical_data.call_count == 2            # refetched despite freshness


def test_retry_survives_transient_error(tmp_path):
    store = BacktestStore(str(tmp_path / "bt.db"))
    kite = MagicMock()
    kite.historical_data.side_effect = [Exception("net blip"), _canned_rows()]
    cfg = _cfg(tmp_path)
    cfg["backtest_data"]["lookback_days"] = 50   # single chunk
    cfg["backtest_data"]["timeframes"] = [{"label": "5min", "interval": "5minute", "max_days": 100}]
    loader = HistoricalLoader(kite, store, cfg)
    res = loader.load_symbol("RELIANCE", 738561)
    assert res["5min"] == 3                       # recovered on retry
