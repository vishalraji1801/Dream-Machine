"""
Live market data streamer.
Wraps KiteTicker WebSocket to stream real-time ticks for all watchlist instruments.
Falls back gracefully — callers check is_connected before using get_latest_quotes().
"""
import threading
import time
from typing import Optional

from kiteconnect import KiteTicker

from src.logger import get_logger

logger = get_logger("data_streamer")


class DataStreamer:
    """
    Streams live MODE_QUOTE ticks via Kite WebSocket.
    Runs in a background thread; thread-safe tick buffer.
    """

    def __init__(self, api_key: str, access_token: str, instruments: dict[str, int],
                 max_tick_age_seconds: float = 0.0):
        """
        instruments: {symbol: instrument_token} map (from DataFetcher._instruments).
        max_tick_age_seconds: if > 0, a buffered tick older than this is treated as
        no-data (stale-tick guard) so the bot never trades on a frozen feed.
        """
        self._ticker = KiteTicker(api_key, access_token)
        self._symbol_to_token = instruments
        self._ticks: dict[int, dict] = {}
        self._tick_time: dict[int, float] = {}
        self._max_tick_age = max_tick_age_seconds
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
        now = time.time()
        with self._lock:
            quotes = {}
            for symbol in symbols:
                token = self._symbol_to_token.get(symbol)
                if token is None:
                    continue
                tick = self._ticks.get(token)
                if tick is None:
                    continue
                if self._max_tick_age > 0:
                    age = now - self._tick_time.get(token, 0.0)
                    if age > self._max_tick_age:
                        logger.warning(f"{symbol}: stale tick ({age:.0f}s old) — skipped")
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
        now = time.time()
        with self._lock:
            for tick in ticks:
                token = tick["instrument_token"]
                self._ticks[token] = tick
                self._tick_time[token] = now

    def _on_close(self, ws, code, reason):
        self._connected = False
        logger.warning(f"KiteTicker closed — code={code} reason={reason}")

    def _on_error(self, ws, code, reason):
        logger.error(f"KiteTicker error — code={code} reason={reason}")

    def _on_reconnect(self, ws, attempts):
        logger.info(f"KiteTicker reconnecting — attempt {attempts}")
