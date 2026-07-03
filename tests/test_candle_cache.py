from unittest.mock import MagicMock

import pandas as pd
import pytest

from src.candle_cache import CandleCache


@pytest.fixture
def cache(tmp_path):
    return CandleCache(cache_dir=str(tmp_path))


@pytest.fixture
def df():
    return pd.DataFrame({
        "timestamp": pd.to_datetime(["2026-07-01 09:15", "2026-07-01 09:20"]),
        "open": [100.0, 101.0], "high": [102.0, 103.0],
        "low": [99.0, 100.0], "close": [101.0, 102.0],
        "volume": [1000, 1500],
    })


def test_get_miss_returns_none(cache):
    assert cache.get("RELIANCE", "5minute", 10) is None


def test_put_then_get_roundtrip(cache, df):
    cache.put("RELIANCE", "5minute", 10, df)
    out = cache.get("RELIANCE", "5minute", 10)
    assert out is not None
    assert len(out) == 2
    assert list(out.columns) == list(df.columns)
    assert out["close"].tolist() == [101.0, 102.0]
    assert pd.api.types.is_datetime64_any_dtype(out["timestamp"])


def test_different_days_key_is_separate(cache, df):
    cache.put("RELIANCE", "5minute", 10, df)
    assert cache.get("RELIANCE", "5minute", 30) is None  # different lookback
    assert cache.get("TCS", "5minute", 10) is None       # different symbol


def test_symbol_with_spaces_and_specials(cache, df):
    cache.put("NIFTY 50", "5minute", 10, df)
    assert cache.get("NIFTY 50", "5minute", 10) is not None
    cache.put("M&M", "5minute", 10, df)
    assert cache.get("M&M", "5minute", 10) is not None
    cache.put("BAJAJ-AUTO", "5minute", 10, df)
    assert cache.get("BAJAJ-AUTO", "5minute", 10) is not None


def test_get_or_fetch_calls_fetch_on_miss(cache, df):
    fetch = MagicMock(return_value=df)
    out = cache.get_or_fetch("RELIANCE", "5minute", 10, fetch)
    fetch.assert_called_once()
    assert len(out) == 2
    # second call hits cache, no refetch
    fetch2 = MagicMock(return_value=None)
    out2 = cache.get_or_fetch("RELIANCE", "5minute", 10, fetch2)
    fetch2.assert_not_called()
    assert len(out2) == 2


def test_get_or_fetch_does_not_cache_none(cache):
    fetch = MagicMock(return_value=None)
    assert cache.get_or_fetch("X", "5minute", 10, fetch) is None
    fetch2 = MagicMock(return_value=None)
    cache.get_or_fetch("X", "5minute", 10, fetch2)
    fetch2.assert_called_once()  # still a miss — None was not cached
