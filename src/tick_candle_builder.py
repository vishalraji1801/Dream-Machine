"""
Tick -> candle builder (V2 P3).

The Kite historical API cannot serve 5-min candles for 200+ symbols every cycle,
so the dynamic-universe design builds candles locally from the WebSocket tick
stream. This aggregates ticks into rolling N-minute OHLCV bars per instrument.

Kite ticks carry cumulative day volume, so per-bar volume is the difference
between the last and first cumulative reading within the bar.
"""
from typing import Optional

import pandas as pd

from src.logger import get_logger

logger = get_logger("tick_candle_builder")


class TickCandleBuilder:
    def __init__(self, interval_seconds: int = 300, max_bars: int = 120):
        self._interval = interval_seconds
        self._max_bars = max_bars
        self._bars: dict[str, list[dict]] = {}

    def add_tick(self, symbol: str, price: float, cum_volume: float, ts_epoch: float) -> None:
        """Fold one tick into the current bar (or open a new one)."""
        bucket = int(ts_epoch // self._interval) * self._interval
        bars = self._bars.setdefault(symbol, [])
        if bars and bars[-1]["bucket"] == bucket:
            b = bars[-1]
            b["high"] = max(b["high"], price)
            b["low"] = min(b["low"], price)
            b["close"] = price
            b["cum_last"] = cum_volume
        else:
            bars.append({
                "bucket": bucket, "open": price, "high": price, "low": price,
                "close": price, "cum_first": cum_volume, "cum_last": cum_volume,
            })
            if len(bars) > self._max_bars:
                bars.pop(0)

    def get_candles(self, symbol: str) -> Optional[pd.DataFrame]:
        """Return completed + current bars as an OHLCV DataFrame (oldest first)."""
        bars = self._bars.get(symbol)
        if not bars:
            return None
        rows = []
        for b in bars:
            rows.append({
                "timestamp": pd.to_datetime(b["bucket"], unit="s"),
                "open": b["open"], "high": b["high"], "low": b["low"],
                "close": b["close"],
                "volume": max(0.0, b["cum_last"] - b["cum_first"]),
            })
        return pd.DataFrame(rows)

    def symbols(self) -> list[str]:
        return list(self._bars)
