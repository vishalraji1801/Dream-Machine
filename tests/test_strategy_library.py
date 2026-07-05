import pandas as pd
import pytest

from src.strategy import STRATEGY_REGISTRY, _crossed_above, _crossed_below, generate_signal


def _df(opens, highs, lows, closes, vols=None):
    n = len(closes)
    return pd.DataFrame({
        "open": opens, "high": highs, "low": lows, "close": closes,
        "volume": vols if vols is not None else [100000] * n,
    })


def _flat(closes):
    """OHLC from a close series with tiny symmetric wicks."""
    return _df([c for c in closes], [c + 0.5 for c in closes],
               [c - 0.5 for c in closes], list(closes))


# ── crossover helpers ─────────────────────────────────────────────────────────

def test_crossed_above():
    a = pd.Series([1, 2, 3, 4]); b = pd.Series([2, 3, 3.5, 3.5])
    assert _crossed_above(a, b) is True
    assert _crossed_below(a, b) is False


def test_crossed_below():
    a = pd.Series([4, 3, 2, 1]); b = pd.Series([2, 2, 2, 2])
    assert _crossed_below(a, b) is True


# base config with every key the existing strategies require
_BASE = {"ema_fast": 9, "ema_slow": 21, "ema_crossover_lookback": 3, "rsi_period": 14,
         "rsi_entry_threshold": 60, "volume_sma_period": 20, "volume_multiplier": 1.5}


# ── every strategy: insufficient data -> HOLD, never raises ───────────────────

@pytest.mark.parametrize("name", list(STRATEGY_REGISTRY))
def test_insufficient_data_holds(name):
    df = _flat([100.0, 101.0, 100.5])           # only 3 rows
    sig = generate_signal("X", df, {**_BASE, "name": name})
    assert sig.direction == "HOLD"


@pytest.mark.parametrize("name", list(STRATEGY_REGISTRY))
def test_returns_valid_signal_on_data(name):
    closes = [100 + (i % 5) for i in range(80)]
    df = _flat(closes)
    if name == "orb":
        df["timestamp"] = pd.date_range("2026-06-01 09:15", periods=80, freq="5min")
    sig = generate_signal("X", df, {**_BASE, "name": name})
    assert sig.direction in ("BUY", "SELL", "HOLD")


# ── targeted firing cases ─────────────────────────────────────────────────────

def test_rsi_reversal_buys_oversold():
    closes = [100 - i * 2 for i in range(20)]     # steep decline -> RSI-2 ~ 0
    df = _flat(closes)
    sig = generate_signal("X", df, {"name": "rsi_reversal", "rsi_rev_period": 2,
                                    "rsi_rev_oversold": 15, "rsi_rev_overbought": 85})
    assert sig.direction == "BUY"
    assert sig.reason == "rsi_oversold_reversal"


def test_rsi_reversal_sells_overbought():
    closes = [100 + i * 2 for i in range(20)]     # steep rally
    df = _flat(closes)
    sig = generate_signal("X", df, {"name": "rsi_reversal", "rsi_rev_period": 2,
                                    "rsi_rev_oversold": 15, "rsi_rev_overbought": 85})
    assert sig.direction == "SELL"


def test_support_resistance_bounce():
    # prior window sits ~100 with lows at 98; last bar dips to 98 and closes back at 100
    closes = [100.0] * 32
    highs = [101.0] * 32
    lows = [98.0] * 32
    opens = [100.0] * 32
    lows[-1] = 98.0
    closes[-1] = 100.0
    df = _df(opens, highs, lows, closes)
    sig = generate_signal("X", df, {"name": "support_resistance", "sr_lookback": 30,
                                    "sr_tol_pct": 0.3})
    assert sig.direction == "BUY"
    assert sig.reason == "support_bounce"


def test_breakout_retest_up():
    # prior resistance 105; last bar closes 106 (breakout) but wicked back to 105 (retest)
    closes = [100.0] * 24
    highs = [105.0] * 24
    lows = [99.0] * 24
    opens = [100.0] * 24
    closes[-1] = 106.0
    highs[-1] = 106.5
    lows[-1] = 105.1
    df = _df(opens, highs, lows, closes)
    sig = generate_signal("X", df, {"name": "breakout_retest", "br_lookback": 20,
                                    "br_tol_pct": 0.3})
    assert sig.direction == "BUY"


def test_price_action_bullish_rejection():
    # last bar: long lower wick piercing swing low, closes up
    closes = [100.0] * 22
    highs = [101.0] * 22
    lows = [99.0] * 22
    opens = [100.0] * 22
    opens[-1] = 99.5; closes[-1] = 100.0; highs[-1] = 100.2; lows[-1] = 97.0
    df = _df(opens, highs, lows, closes)
    sig = generate_signal("X", df, {"name": "price_action_levels", "pa_lookback": 20,
                                    "pa_tol_pct": 0.5})
    assert sig.direction == "BUY"
    assert sig.reason == "bullish_rejection"


def test_smc_liquidity_sweep_long():
    # last bar sweeps below swing low (95) then reclaims (closes 100)
    closes = [100.0] * 22
    highs = [101.0] * 22
    lows = [99.0] * 22
    opens = [100.0] * 22
    lows[-1] = 98.0; closes[-1] = 100.0            # swing low 99, swept to 98, reclaimed
    df = _df(opens, highs, lows, closes)
    sig = generate_signal("X", df, {"name": "smc", "smc_lookback": 20})
    assert sig.direction == "BUY"
    assert sig.reason == "smc_liquidity_sweep_long"


def test_ema_crossover_fires_on_upturn():
    # long decline then sharp sustained rally -> fast EMA crosses above slow
    closes = [200 - i for i in range(60)] + [140 + i * 4 for i in range(20)]
    df = _flat(closes)
    # scan the tail: at some recent bar the crossover BUY should trigger
    fired = False
    for end in range(len(df) - 10, len(df)):
        sig = generate_signal("X", df.iloc[:end + 1], {"name": "ema_crossover",
                                                       "ec_fast": 20, "ec_slow": 50})
        if sig.direction == "BUY":
            fired = True
            break
    assert fired
