from unittest.mock import MagicMock, patch
import pytest

from src.data_streamer import DataStreamer


@pytest.fixture
def instruments():
    return {"RELIANCE": 738561, "TCS": 2953217, "INFY": 408065}


@pytest.fixture
def streamer(instruments):
    with patch("src.data_streamer.KiteTicker") as MockTicker:
        mock_ticker = MagicMock()
        MockTicker.return_value = mock_ticker
        ds = DataStreamer("api_key", "access_token", instruments)
        ds._ticker = mock_ticker
        yield ds


def _make_tick(token, ltp=2850.0, open_=2840.0, high=2870.0, low=2835.0, close=2860.0, volume=500000):
    return {
        "instrument_token": token,
        "last_price": ltp,
        "ohlc": {"open": open_, "high": high, "low": low, "close": close},
        "volume": volume,
    }


# ── stale-tick guard (V2 P1) ──────────────────────────────────────────────────

def test_fresh_tick_returned_within_age(instruments):
    with patch("src.data_streamer.KiteTicker"):
        ds = DataStreamer("k", "t", instruments, max_tick_age_seconds=30)
    ds._connected = True
    ds._on_ticks(MagicMock(), [_make_tick(738561)])
    quotes = ds.get_latest_quotes(["RELIANCE"])
    assert quotes is not None and "RELIANCE" in quotes


def test_stale_tick_skipped(instruments):
    with patch("src.data_streamer.KiteTicker"):
        ds = DataStreamer("k", "t", instruments, max_tick_age_seconds=30)
    ds._connected = True
    with patch("src.data_streamer.time.time", return_value=1000.0):
        ds._on_ticks(MagicMock(), [_make_tick(738561)])
    with patch("src.data_streamer.time.time", return_value=1040.0):  # 40s later > 30s
        quotes = ds.get_latest_quotes(["RELIANCE"])
    assert quotes is None  # only symbol was stale -> nothing to return


def test_age_guard_disabled_when_zero(instruments):
    with patch("src.data_streamer.KiteTicker"):
        ds = DataStreamer("k", "t", instruments, max_tick_age_seconds=0)
    ds._connected = True
    with patch("src.data_streamer.time.time", return_value=1000.0):
        ds._on_ticks(MagicMock(), [_make_tick(738561)])
    with patch("src.data_streamer.time.time", return_value=999999.0):
        quotes = ds.get_latest_quotes(["RELIANCE"])
    assert quotes is not None  # guard off -> stale tick still returned


# ── connect / disconnect ──────────────────────────────────────────────────────

def test_connect_calls_ticker_connect(streamer):
    streamer.connect()
    streamer._ticker.connect.assert_called_once_with(threaded=True)


def test_disconnect_closes_ticker(streamer):
    streamer._connected = True
    streamer.disconnect()
    streamer._ticker.close.assert_called_once()
    assert not streamer.is_connected


# ── on_connect ────────────────────────────────────────────────────────────────

def test_on_connect_subscribes_all_tokens(streamer, instruments):
    ws = MagicMock()
    streamer._on_connect(ws, {})
    expected_tokens = list(instruments.values())
    ws.subscribe.assert_called_once_with(expected_tokens)


def test_on_connect_sets_mode_quote(streamer, instruments):
    ws = MagicMock()
    streamer._on_connect(ws, {})
    ws.set_mode.assert_called_once_with(ws.MODE_QUOTE, list(instruments.values()))


def test_on_connect_sets_connected_true(streamer):
    ws = MagicMock()
    assert not streamer.is_connected
    streamer._on_connect(ws, {})
    assert streamer.is_connected


# ── tick buffering ────────────────────────────────────────────────────────────

def test_on_ticks_buffers_by_token(streamer):
    tick = _make_tick(738561)
    streamer._on_ticks(MagicMock(), [tick])
    assert 738561 in streamer._ticks
    assert streamer._ticks[738561]["last_price"] == 2850.0


def test_on_ticks_overwrites_with_latest(streamer):
    streamer._on_ticks(MagicMock(), [_make_tick(738561, ltp=2850.0)])
    streamer._on_ticks(MagicMock(), [_make_tick(738561, ltp=2860.0)])
    assert streamer._ticks[738561]["last_price"] == 2860.0


def test_on_ticks_buffers_multiple_instruments(streamer):
    streamer._on_ticks(MagicMock(), [
        _make_tick(738561), _make_tick(2953217, ltp=3500.0)
    ])
    assert 738561 in streamer._ticks
    assert 2953217 in streamer._ticks


# ── get_latest_quotes ─────────────────────────────────────────────────────────

def test_get_latest_quotes_returns_none_when_not_connected(streamer):
    assert streamer.is_connected is False
    assert streamer.get_latest_quotes(["RELIANCE"]) is None


def test_get_latest_quotes_returns_correct_fields(streamer):
    streamer._connected = True
    streamer._ticks[738561] = _make_tick(738561, ltp=2855.0, open_=2840.0,
                                          high=2870.0, low=2835.0, close=2860.0, volume=500000)
    quotes = streamer.get_latest_quotes(["RELIANCE"])
    assert quotes is not None
    r = quotes["RELIANCE"]
    assert r["ltp"] == 2855.0
    assert r["open"] == 2840.0
    assert r["high"] == 2870.0
    assert r["volume"] == 500000


def test_get_latest_quotes_skips_symbol_without_token(streamer):
    streamer._connected = True
    quotes = streamer.get_latest_quotes(["UNKNOWN_XYZ"])
    assert quotes is None


def test_get_latest_quotes_skips_symbol_with_no_tick_yet(streamer):
    streamer._connected = True
    # Connected but no ticks buffered yet
    quotes = streamer.get_latest_quotes(["RELIANCE"])
    assert quotes is None


def test_get_latest_quotes_returns_only_requested_symbols(streamer):
    streamer._connected = True
    streamer._ticks[738561] = _make_tick(738561)
    streamer._ticks[2953217] = _make_tick(2953217, ltp=3500.0)
    quotes = streamer.get_latest_quotes(["RELIANCE"])
    assert "RELIANCE" in quotes
    assert "TCS" not in quotes


# ── close/error/reconnect callbacks ──────────────────────────────────────────

def test_on_close_sets_not_connected(streamer):
    streamer._connected = True
    streamer._on_close(MagicMock(), 1000, "normal close")
    assert not streamer.is_connected


def test_on_error_does_not_raise(streamer):
    streamer._on_error(MagicMock(), 503, "service unavailable")


def test_on_reconnect_does_not_raise(streamer):
    streamer._on_reconnect(MagicMock(), 3)
