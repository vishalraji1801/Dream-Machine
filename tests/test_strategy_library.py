"""Strategy library — each mined strategy triggers and returns a sane signal."""
import pandas as pd

from src.strategy import STRATEGY_REGISTRY, generate_signal
from src.strategy_library import (bb_mean_reversion, donchian_trend_tsl, orb_nifty,
                                  supertrend)

CFG = {"atr_period": 14, "sl_mode": "pct", "stop_loss_pct": 1.0, "target_pct": 2.0,
       "ema_fast": 9, "ema_slow": 21, "rsi_period": 14, "volume_sma_period": 20}


def _ohlc(closes, highs=None, lows=None, vols=None, ts=None):
    n = len(closes)
    df = pd.DataFrame({
        "open": [c - 0.2 for c in closes],
        "high": highs if highs is not None else [c + 1 for c in closes],
        "low": lows if lows is not None else [c - 1 for c in closes],
        "close": closes,
        "volume": vols if vols is not None else [500_000] * n,
    })
    if ts is not None:
        df["timestamp"] = pd.to_datetime(ts)
    return df


def test_registry_registered():
    assert {"bb_mean_reversion", "donchian_trend_tsl", "supertrend", "orb_nifty"} <= set(STRATEGY_REGISTRY)


# ── E-005 Bollinger mean-reversion ────────────────────────────────────────────

def test_bb_mean_reversion_buys_oversold_pullback():
    closes = [100 + 0.5 * i for i in range(219)] + [190.0]   # uptrend, sharp dip last bar
    sig = bb_mean_reversion("X", _ohlc(closes), CFG)
    assert sig.direction == "BUY"
    assert sig.reason == "bb_mean_reversion"
    assert sig.stop_loss < sig.entry_price < sig.target       # entry below, mean above


def test_bb_holds_without_pullback():
    closes = [100 + 0.5 * i for i in range(220)]              # uptrend, no dip
    assert bb_mean_reversion("X", _ohlc(closes), CFG).direction == "HOLD"


def test_bb_insufficient_data():
    assert bb_mean_reversion("X", _ohlc([100] * 50), CFG).reason == "insufficient_data"


# ── E-003 Donchian breakout ───────────────────────────────────────────────────

def test_donchian_long_on_new_high():
    closes = [100 + i for i in range(210)]                    # steadily rising -> new high
    sig = donchian_trend_tsl("X", _ohlc(closes), CFG)
    assert sig.direction == "BUY" and sig.reason == "donchian_breakout_long"
    assert sig.stop_loss < sig.entry_price < sig.target


def test_donchian_short_on_new_low():
    closes = [400 - i for i in range(210)]                    # steadily falling -> new low
    sig = donchian_trend_tsl("X", _ohlc(closes), CFG)
    assert sig.direction == "SELL" and sig.reason == "donchian_breakout_short"
    assert sig.stop_loss > sig.entry_price > sig.target


# ── E-001 Supertrend ──────────────────────────────────────────────────────────

def test_supertrend_flip_up_buys():
    closes = [1000 - i * 6 for i in range(28)] + [1000 - 27 * 6 + 120]   # downtrend then jump
    sig = supertrend("X", _ohlc(closes), {**CFG, "supertrend_period": 10, "supertrend_mult": 3.0})
    assert sig.direction == "BUY" and sig.reason == "supertrend_flip_up"


# ── E-008 Opening Range Breakout ──────────────────────────────────────────────

def test_orb_breaks_opening_range_high():
    day = "2026-07-10 "
    ts = [day + "09:15", day + "09:30", day + "09:45"]
    closes = [103.0, 104.0, 108.0]
    highs = [105.0, 104.5, 109.0]     # OR high = 105 (first bar)
    lows = [101.0, 103.0, 106.0]
    vols = [400_000, 300_000, 1_500_000]
    sig = orb_nifty("X", _ohlc(closes, highs, lows, vols, ts),
                    {**CFG, "orb_or_end": "09:30", "orb_max_stop_cap_pts": 30, "orb_r_multiple": 2.0})
    assert sig.direction == "BUY" and sig.reason == "orb_break_high"
    assert sig.stop_loss < sig.entry_price < sig.target


def test_orb_holds_without_timestamp():
    assert orb_nifty("X", _ohlc([100, 101, 102]), CFG).reason == "no_timestamp"


# ── dispatch through generate_signal ──────────────────────────────────────────

def test_generate_signal_dispatches_to_library():
    closes = [1000 - i * 6 for i in range(28)] + [1000 - 27 * 6 + 120]
    sig = generate_signal("X", _ohlc(closes),
                          {**CFG, "name": "supertrend", "supertrend_period": 10,
                           "supertrend_mult": 3.0})
    assert sig.direction in ("BUY", "SELL", "HOLD")
