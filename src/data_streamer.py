"""
Live market data streamer.
Wraps KiteTicker WebSocket to stream real-time ticks for all watchlist instruments.
Falls back gracefully — callers check is_connected before using get_latest_quotes().
"""
import threading
from typing import Optional

from kiteconnect import KiteTicker

from src.logger import get_logger

logger = get_logger("data_streamer")


class DataStreamer:
    """
    Streams live MODE_QUOTE ticks via Kite WebSocket.
    Runs in a background thread; thread-safe tick buffer.
    """

    def __init__(self, api_key: str, access_token: str, instruments: dict[str, int]):
        """
        instruments: {symbol: instrument_token} map (from DataFetcher._instruments).
        """
        self._ticker = KiteTicker(api_key, access_token)
        self._symbol_to_token = instruments
        self._token_to_symbol = {v: k for k, v in instruments.items()}
        self._ticks: dict[int, dict] = {}
        self._connected = False
        self._lock = threading.Lock()

        self._ticker.on_connect = self._on_connect
        self._ticker.on_ticks = self._on_ticks
        self._ticker.on_close = self._on_close
        self._ticker.on_error = self._on_error
        self._ticker.on_reconnect = self._on_reconnect

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def connect(self) -> None:
        """Start the WebSocket in a background thread (non-blocking)."""
        logger.info(f"KiteTicker connecting — {len(self._symbol_to_token)} instruments")
        self._ticker.connect(threaded=True)

    def disconnect(self) -> None:
        """Close the WebSocket connection."""
        self._ticker.close()
        self._connected = False
        logger.info("KiteTicker disconnected")

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ── Data access ───────────────────────────────────────────────────────────

    def get_latest_quotes(self, symbols: list[str]) -> Optional[dict[str, dict]]:
        """
        Return buffered live ticks in the same format as DataFetcher.get_quotes().
        Returns None if not connected or no data buffered for any requested symbol.
        """
        if not self._connected:
            return None
        with self._lock:
            quotes = {}
            for symbol in symbols:
                token = self._symbol_to_token.get(symbol)
                if token is None:
                    continue
                tick = self._ticks.get(token)
                if tick is None:
                    continue
                ohlc = tick.get("ohlc", {})
                quotes[symbol] = {
                    "ltp":    tick.get("last_price", 0.0),
                    "open":   ohlc.get("open", 0.0),
                    "high":   ohlc.get("high", 0.0),
                    "low":    ohlc.get("low", 0.0),
                    "close":  ohlc.get("close", 0.0),
                    "volume": tick.get("volume", 0),
                }
        return quotes if quotes else None

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def _on_connect(self, ws, response):
        tokens = list(self._symbol_to_token.values())
        ws.subscribe(tokens)
        ws.set_mode(ws.MODE_QUOTE, tokens)
        self._connected = True
        logger.info(f"KiteTicker subscribed to {len(tokens)} instruments in MODE_QUOTE")

    def _on_ticks(self, ws, ticks):
        with self._lock:
            for tick in ticks:
                self._ticks[tick["instrument_token"]] = tick

    def _on_close(self, ws, code, reason):
        self._connected = False
        logger.warning(f"KiteTicker closed — code={code} reason={reason}")

    def _on_error(self, ws, code, reason):
        logger.error(f"KiteTicker error — code={code} reason={reason}")

    def _on_reconnect(self, ws, attempts):
        logger.info(f"KiteTicker reconnecting — attempt {attempts}")
