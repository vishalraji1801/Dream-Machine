import pandas as pd
import pytest

from src.backtest_store import BacktestStore


@pytest.fixture
def store(tmp_path):
    return BacktestStore(path=str(tmp_path / "bt.db"))


def _df(times, base=100.0):
    return pd.DataFrame({
        "timestamp": pd.to_datetime(times),
        "open": [base] * len(times), "high": [base + 1] * len(times),
        "low": [base - 1] * len(times), "close": [base + 0.5] * len(times),
        "volume": [1000] * len(times),
    })


def test_upsert_and_get_roundtrip(store):
    df = _df(["2026-06-01 09:15", "2026-06-01 09:20"])
    n = store.upsert_candles("RELIANCE", "5min", df)
    assert n == 2
    out = store.get_candles("RELIANCE", "5min")
    assert len(out) == 2
    assert pd.api.types.is_datetime64_any_dtype(out["timestamp"])
    assert out.iloc[0]["close"] == 100.5


def test_upsert_is_idempotent_on_overlap(store):
    df = _df(["2026-06-01 09:15", "2026-06-01 09:20"])
    store.upsert_candles("RELIANCE", "5min", df)
    store.upsert_candles("RELIANCE", "5min", df)  # same timestamps again
    assert store.candle_count("RELIANCE", "5min") == 2  # not duplicated


def test_timeframes_are_isolated(store):
    store.upsert_candles("RELIANCE", "5min", _df(["2026-06-01 09:15"]))
    store.upsert_candles("RELIANCE", "1hr", _df(["2026-06-01 09:15"]))
    assert store.candle_count("RELIANCE", "5min") == 1
    assert store.candle_count("RELIANCE", "1hr") == 1


def test_has_fresh_today_true(store):
    store.upsert_candles("RELIANCE", "5min", _df(["2026-06-01 09:15"]))
    assert store.has_fresh("RELIANCE", "5min") is True
    assert store.has_fresh("RELIANCE", "5min", day="2020-01-01") is False


def test_has_fresh_false_when_absent(store):
    assert store.has_fresh("TCS", "5min") is False


def test_symbols_distinct(store):
    store.upsert_candles("RELIANCE", "5min", _df(["2026-06-01 09:15"]))
    store.upsert_candles("TCS", "5min", _df(["2026-06-01 09:15"]))
    assert set(store.symbols("5min")) == {"RELIANCE", "TCS"}


def test_clear(store):
    store.upsert_candles("RELIANCE", "5min", _df(["2026-06-01 09:15"]))
    store.clear()
    assert store.get_candles("RELIANCE", "5min") is None
    assert store.has_fresh("RELIANCE", "5min") is False


def test_empty_df_noop(store):
    assert store.upsert_candles("X", "5min", pd.DataFrame()) == 0
    assert store.upsert_candles("X", "5min", None) == 0
