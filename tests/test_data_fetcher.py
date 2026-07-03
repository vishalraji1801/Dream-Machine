from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.data_fetcher import DataFetcher


@pytest.fixture
def cfg():
    return {
        "trading": {
            "exchange": "NSE",
            "timeframe": "5minute",
        }
    }


@pytest.fixture
def mock_kite():
    return MagicMock()


@pytest.fixture
def fetcher(mock_kite, cfg):
    return DataFetcher(mock_kite, cfg)


def _instruments():
    return [
        {"tradingsymbol": "RELIANCE", "instrument_token": 738561},
        {"tradingsymbol": "TCS",      "instrument_token": 2953217},
        {"tradingsymbol": "INFY",     "instrument_token": 408065},
    ]


def _candles():
    return [
        {"date": datetime(2026, 7, 3, 9, 15), "open": 2840.0, "high": 2855.0, "low": 2838.0, "close": 2850.0, "volume": 120000},
        {"date": datetime(2026, 7, 3, 9, 20), "open": 2850.0, "high": 2862.0, "low": 2847.0, "close": 2858.0, "volume": 95000},
        {"date": datetime(2026, 7, 3, 9, 25), "open": 2858.0, "high": 2872.0, "low": 2855.0, "close": 2865.0, "volume": 140000},
    ]


def _quote_response(symbol="RELIANCE"):
    return {
        f"NSE:{symbol}": {
            "last_price": 2865.0,
            "ohlc": {"open": 2840.0, "high": 2870.0, "low": 2835.0, "close": 2860.0},
            "volume": 500000,
        }
    }


# ── load_instruments ──────────────────────────────────────────────────────────

def test_load_instruments_success(fetcher, mock_kite):
    mock_kite.instruments.return_value = _instruments()
    assert fetcher.load_instruments(["RELIANCE", "TCS"]) is True
    assert fetcher._instruments["RELIANCE"] == 738561
    assert fetcher._instruments["TCS"] == 2953217


def test_load_instruments_skips_unknown_symbol(fetcher, mock_kite):
    mock_kite.instruments.return_value = _instruments()
    assert fetcher.load_instruments(["RELIANCE", "UNKNOWN_XYZ"]) is True
    assert "UNKNOWN_XYZ" not in fetcher._instruments


def test_load_instruments_returns_false_on_api_failure(fetcher, mock_kite):
    mock_kite.instruments.side_effect = Exception("API down")
    assert fetcher.load_instruments(["RELIANCE"]) is False


# ── get_quotes ────────────────────────────────────────────────────────────────

def test_get_quotes_returns_correct_fields(fetcher, mock_kite):
    mock_kite.quote.return_value = _quote_response()
    quotes = fetcher.get_quotes(["RELIANCE"])
    assert quotes is not None
    r = quotes["RELIANCE"]
    assert r["ltp"] == 2865.0
    assert r["open"] == 2840.0
    assert r["volume"] == 500000


def test_get_quotes_formats_instrument_keys(fetcher, mock_kite):
    mock_kite.quote.return_value = _quote_response()
    fetcher.get_quotes(["RELIANCE"])
    mock_kite.quote.assert_called_once_with(["NSE:RELIANCE"])


def test_get_quotes_returns_none_after_retries(fetcher, mock_kite):
    mock_kite.quote.side_effect = Exception("Network error")
    with patch("src.data_fetcher.time.sleep"):
        assert fetcher.get_quotes(["RELIANCE"]) is None


def test_get_quotes_skips_missing_symbol_in_response(fetcher, mock_kite):
    mock_kite.quote.return_value = {}
    quotes = fetcher.get_quotes(["RELIANCE"])
    assert quotes == {}


def test_get_quotes_multiple_symbols(fetcher, mock_kite):
    mock_kite.quote.return_value = {
        **_quote_response("RELIANCE"),
        **_quote_response("TCS"),
    }
    quotes = fetcher.get_quotes(["RELIANCE", "TCS"])
    assert len(quotes) == 2


# ── get_candles ───────────────────────────────────────────────────────────────

def test_get_candles_returns_dataframe(fetcher, mock_kite):
    fetcher._instruments["RELIANCE"] = 738561
    mock_kite.historical_data.return_value = _candles()
    df = fetcher.get_candles("RELIANCE")
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]


def test_get_candles_correct_row_count(fetcher, mock_kite):
    fetcher._instruments["RELIANCE"] = 738561
    mock_kite.historical_data.return_value = _candles()
    df = fetcher.get_candles("RELIANCE")
    assert len(df) == 3


def test_get_candles_sorted_chronologically(fetcher, mock_kite):
    fetcher._instruments["INFY"] = 408065
    mock_kite.historical_data.return_value = list(reversed(_candles()))
    df = fetcher.get_candles("INFY")
    assert df["timestamp"].is_monotonic_increasing


def test_get_candles_returns_none_without_token(fetcher, mock_kite):
    assert fetcher.get_candles("NOTLOADED") is None


def test_get_candles_returns_none_on_empty_response(fetcher, mock_kite):
    fetcher._instruments["TCS"] = 2953217
    mock_kite.historical_data.return_value = []
    assert fetcher.get_candles("TCS") is None


def test_get_candles_returns_none_after_retries(fetcher, mock_kite):
    fetcher._instruments["RELIANCE"] = 738561
    mock_kite.historical_data.side_effect = Exception("persistent error")
    with patch("src.data_fetcher.time.sleep"):
        assert fetcher.get_candles("RELIANCE") is None


# ── retry logic ───────────────────────────────────────────────────────────────

def test_retry_succeeds_on_second_attempt(fetcher, mock_kite):
    fetcher._instruments["RELIANCE"] = 738561
    mock_kite.historical_data.side_effect = [Exception("timeout"), _candles()]
    with patch("src.data_fetcher.time.sleep") as mock_sleep:
        df = fetcher.get_candles("RELIANCE")
    assert df is not None and len(df) == 3
    mock_sleep.assert_called_once_with(1)


def test_retry_sleeps_between_attempts(fetcher, mock_kite):
    fetcher._instruments["RELIANCE"] = 738561
    mock_kite.historical_data.side_effect = [
        Exception("err1"), Exception("err2"), _candles()
    ]
    with patch("src.data_fetcher.time.sleep") as mock_sleep:
        df = fetcher.get_candles("RELIANCE")
    assert df is not None
    assert mock_sleep.call_count == 2


def test_no_sleep_after_final_failure(fetcher, mock_kite):
    fetcher._instruments["RELIANCE"] = 738561
    mock_kite.historical_data.side_effect = Exception("persistent")
    with patch("src.data_fetcher.time.sleep") as mock_sleep:
        fetcher.get_candles("RELIANCE")
    assert mock_sleep.call_count == 2  # sleeps before attempts 2 and 3 only
