"""
Tick -> candle builder (V2 P3 / SCRUM-106).

Builds trading-timeframe OHLCV bars locally from the WebSocket tick stream so
the live/paper cycle makes ZERO per-cycle REST candle calls. Closed history is
seeded once (e.g., from one REST fetch at startup); ticks continue the series.

Kite ticks carry cumulative day volume (`volume_traded`), so per-bar volume is
last-minus-first cumulative within the bar. Seeded bars keep their fetched
volume as-is. Thread-safe: ticks arrive on the streamer thread while the main
loop reads candles.

Known, accepted imprecision: if seeding happens mid-bar, the currently forming
bar's volume counts only ticks seen after seeding; it self-corrects on the next
bar. (OHLC of that bar is likewise tick-only.)
"""
import threading
from typing import Optional

import pandas as pd

from src.logger import get_logger

logger = get_logger("tick_candle_builder")

_IST = "Asia/Kolkata"


class TickCandleBuilder:
    def __init__(self, interval_seconds: int = 300, max_bars: int = 120):
        self._interval = interval_seconds
        self._max_bars = max_bars
        self._bars: dict[str, list[dict]] = {}
        self._lock = threading.Lock()

    # ── writes ──────────────────────────────────────────────────────────────────

    def add_tick(self, symbol: str, price: float, cum_volume: float, ts_epoch: float) -> None:
        """Fold one tick into the current bar (or open a new one)."""
        bucket = int(ts_epoch // self._interval) * self._interval
        with self._lock:
            bars = self._bars.setdefault(symbol, [])
            if bars and bars[-1]["bucket"] == bucket and "cum_first" in bars[-1]:
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

    def seed(self, symbol: str, df: pd.DataFrame, now_epoch: Optional[float] = None) -> int:
        """
        Preload CLOSED historical bars (e.g., one REST fetch at startup) so
        subsequent ticks continue the series. Any bar at/after the currently
        forming bucket is dropped (ticks own it). Returns bars seeded.
        """
        if df is None or df.empty:
            return 0
        cur_bucket = (int(now_epoch // self._interval) * self._interval
                      if now_epoch is not None else None)
        bars = []
        for _, r in df.iterrows():
            ts = pd.Timestamp(r["timestamp"])
            if ts.tzinfo is None:
                ts = ts.tz_localize(_IST)
            bucket = int(ts.timestamp() // self._interval) * self._interval
            if cur_bucket is not None and bucket >= cur_bucket:
                continue
            bars.append({"bucket": bucket, "open": float(r["open"]),
                         "high": float(r["high"]), "low": float(r["low"]),
                         "close": float(r["close"]), "vol_fixed": float(r["volume"])})
        bars.sort(key=lambda b: b["bucket"])
        bars = bars[-self._max_bars:]
        with self._lock:
            self._bars[symbol] = bars
        return len(bars)

    # ── reads ───────────────────────────────────────────────────────────────────

    def get_candles(self, symbol: str) -> Optional[pd.DataFrame]:
        """Seeded + tick-built bars as an OHLCV DataFrame (oldest first),
        timestamps tz-aware IST to match Kite's REST candles."""
        with self._lock:
            bars = list(self._bars.get(symbol) or [])
        if not bars:
            return None
        rows = []
        for b in bars:
            volume = b["vol_fixed"] if "vol_fixed" in b else max(0.0, b["cum_last"] - b["cum_first"])
            rows.append({
                "timestamp": pd.Timestamp(b["bucket"], unit="s", tz="UTC").tz_convert(_IST),
                "open": b["open"], "high": b["high"], "low": b["low"],
                "close": b["close"], "volume": volume,
            })
        return pd.DataFrame(rows)

    def bar_count(self, symbol: str) -> int:
        with self._lock:
            return len(self._bars.get(symbol) or [])

    def symbols(self) -> list[str]:
        with self._lock:
            return list(self._bars)
