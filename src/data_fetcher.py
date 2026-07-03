"""
Market data fetcher.
Fetches live quotes and 5-minute OHLCV candles from Kite, with retry logic.
"""
import time
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
from kiteconnect import KiteConnect
from kiteconnect import exceptions as kite_exc

from src.logger import get_logger

logger = get_logger("data_fetcher")

_RETRY_DELAYS = [1, 3, 5]  # seconds between retry attempts


class DataFetcher:
    def __init__(self, kite: KiteConnect, cfg: dict):
        self._kite = kite
        self._exchange = cfg["trading"]["exchange"]
        self._interval = cfg["trading"]["timeframe"]
        self._instruments: dict[str, int] = {}  # symbol -> instrument_token

    # ── Startup ───────────────────────────────────────────────────────────────

    def load_instruments(self, symbols: list[str]) -> bool:
        """Fetch and cache instrument tokens for watchlist symbols. Call once at startup."""
        try:
            all_instruments = self._with_retry(
                lambda: self._kite.instruments(self._exchange)
            )
            lookup = {i["tradingsymbol"]: i["instrument_token"] for i in all_instruments}
            missing = []
            for symbol in symbols:
                if symbol in lookup:
                    self._instruments[symbol] = lookup[symbol]
                else:
                    missing.append(symbol)
            if missing:
                logger.warning(f"Instrument tokens not found for: {missing}")
            logger.info(f"Loaded {len(self._instruments)} instrument tokens from {self._exchange}")
            return True
        except Exception as exc:
            logger.error(f"load_instruments failed: {exc}")
            return False

    # ── Live data ─────────────────────────────────────────────────────────────

    def get_quotes(self, symbols: list[str]) -> Optional[dict[str, dict]]:
        """
        Fetch live LTP, OHLC, and volume for given symbols (FR-05).
        Returns dict keyed by symbol, or None after retries exhausted.
        """
        keys = [f"{self._exchange}:{s}" for s in symbols]
        try:
            raw = self._with_retry(lambda: self._kite.quote(keys))
        except Exception as exc:
            logger.error(f"get_quotes failed after retries: {exc}")
            return None

        quotes = {}
        for symbol in symbols:
            key = f"{self._exchange}:{symbol}"
            if key not in raw:
                logger.warning(f"No quote data returned for {symbol}")
                continue
            q = raw[key]
            depth = q.get("depth") or {}
            buy_depth = depth.get("buy") or []
            sell_depth = depth.get("sell") or []
            quotes[symbol] = {
                "ltp":    q["last_price"],
                "open":   q["ohlc"]["open"],
                "high":   q["ohlc"]["high"],
                "low":    q["ohlc"]["low"],
                "close":  q["ohlc"]["close"],
                "volume": q["volume"],
                "bid":    buy_depth[0].get("price") if buy_depth else None,
                "ask":    sell_depth[0].get("price") if sell_depth else None,
            }
        logger.info(f"Quotes fetched: {len(quotes)}/{len(symbols)} symbols")
        return quotes

    # ── Historical candles ────────────────────────────────────────────────────

    def get_candles(self, symbol: str, lookback_days: int = 2) -> Optional[pd.DataFrame]:
        """
        Fetch historical OHLCV candles for indicator computation (FR-06).
        Returns DataFrame with columns [timestamp, open, high, low, close, volume],
        sorted chronologically. Returns None after retries exhausted.
        """
        token = self._instruments.get(symbol)
        if not token:
            logger.error(f"No instrument token for {symbol} — call load_instruments() first")
            return None

        to_date = datetime.now()
        from_date = to_date - timedelta(days=lookback_days)

        try:
            raw = self._with_retry(
                lambda: self._kite.historical_data(token, from_date, to_date, self._interval)
            )
        except Exception as exc:
            logger.error(f"get_candles({symbol}) failed after retries: {exc}")
            return None

        if not raw:
            logger.warning(f"{symbol}: empty candle response")
            return None

        df = pd.DataFrame(raw)
        df.rename(columns={"date": "timestamp"}, inplace=True)
        df = df[["timestamp", "open", "high", "low", "close", "volume"]]
        df = df.sort_values("timestamp").reset_index(drop=True)
        logger.info(f"{symbol}: {len(df)} candles fetched ({self._interval}, {lookback_days}d)")
        return df

    # ── Retry helper ──────────────────────────────────────────────────────────

    def _with_retry(self, fn, retries: int = 3):
        """Call fn() up to `retries` times with backoff. Raises on final failure (FR-07)."""
        for attempt in range(retries):
            try:
                return fn()
            except (kite_exc.NetworkException, kite_exc.DataException,
                    kite_exc.GeneralException) as exc:
                logger.warning(f"Kite API error attempt {attempt + 1}/{retries}: {exc}")
            except Exception as exc:
                logger.warning(f"Unexpected error attempt {attempt + 1}/{retries}: {exc}")
            if attempt < retries - 1:
                delay = _RETRY_DELAYS[attempt]
                logger.info(f"Retrying in {delay}s...")
                time.sleep(delay)
        raise Exception(f"All {retries} retries exhausted")
