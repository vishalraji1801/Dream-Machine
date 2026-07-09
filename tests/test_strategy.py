import pandas as pd
import pytest

from src.strategy import (STRATEGY_REGISTRY, TradeSignal, _atr, _sl_target,
                          _supertrend_dir, generate_signal, market_regime)


@pytest.fixture
def cfg():
    return {
        "ema_fast": 9,
        "ema_slow": 21,
        "ema_crossover_lookback": 3,
        "rsi_period": 14,
        "volume_sma_period": 20,
        "volume_multiplier": 1.5,
        "stop_loss_pct": 1.0,
        "target_pct": 2.0,
    }


def _make_df(n: int = 80, trend: str = "up", vol_spike: bool = False) -> pd.DataFrame:
    """Synthetic OHLCV with a controllable trend."""
    base = 1000.0
    step = 2.0 if trend == "up" else -2.0
    closes = [base + i * step for i in range(n)]
    vols = [500_000] * n
    if vol_spike:
        vols[-1] = 1_000_000
    return pd.DataFrame({
        "open":   [c - 1 for c in closes],
        "high":   [c + 3 for c in closes],
        "low":    [c - 3 for c in closes],
        "close":  closes,
        "volume": vols,
    })


# ── dispatcher: clean-slate registry ─────────────────────────────────────────

def test_no_strategy_registered_holds(cfg):
    """With an empty registry the engine takes no trades."""
    sig = generate_signal("RELIANCE", _make_df(n=80), cfg)
    assert isinstance(sig, TradeSignal)
    assert sig.direction == "HOLD"
    assert sig.reason == "no_strategy"
    assert sig.entry_price == 0.0 and sig.stop_loss == 0.0 and sig.target == 0.0


def test_unknown_name_holds(cfg):
    sig = generate_signal("X", _make_df(n=80), {**cfg, "name": "nonexistent"})
    assert sig.direction == "HOLD"
    assert sig.reason == "no_strategy"


def test_dispatcher_routes_to_registered_strategy(cfg):
    """A strategy added to the registry is dispatched by name."""
    def always_buy(symbol, df, c):
        entry = float(df["close"].iloc[-1])
        sl, tgt = _sl_target(df, entry, "BUY", c)
        return TradeSignal("BUY", symbol, entry, sl, tgt, "always_buy")

    STRATEGY_REGISTRY["always_buy"] = always_buy
    try:
        sig = generate_signal("X", _make_df(n=80), {**cfg, "name": "always_buy"})
    finally:
        del STRATEGY_REGISTRY["always_buy"]
    assert sig.direction == "BUY"
    assert sig.reason == "always_buy"
    assert sig.stop_loss < sig.entry_price < sig.target


def test_registry_empty_by_default():
    assert STRATEGY_REGISTRY == {}


# ── indicator toolkit ────────────────────────────────────────────────────────

def _ohlc(closes, vols=None, highs=None, lows=None, timestamps=None):
    n = len(closes)
    df = pd.DataFrame({
        "open":   [c - 0.5 for c in closes],
        "high":   highs if highs is not None else [c + 2 for c in closes],
        "low":    lows if lows is not None else [c - 2 for c in closes],
        "close":  closes,
        "volume": vols if vols is not None else [500_000] * n,
    })
    if timestamps is not None:
        df["timestamp"] = pd.to_datetime(timestamps)
    return df


def test_atr_positive_for_ranged_data():
    df = _ohlc([100 + i for i in range(30)])
    assert _atr(df, 14) > 0


def test_atr_zero_when_insufficient():
    assert _atr(_ohlc([100, 101, 102]), 14) == 0.0


def test_sl_target_pct_mode_buy():
    df = _ohlc([100.0] * 30)
    sl, tgt = _sl_target(df, 100.0, "BUY", {"stop_loss_pct": 1.0, "target_pct": 2.0})
    assert sl == 99.0 and tgt == 102.0


def test_sl_target_pct_mode_sell():
    df = _ohlc([100.0] * 30)
    sl, tgt = _sl_target(df, 100.0, "SELL", {"stop_loss_pct": 1.0, "target_pct": 2.0})
    assert sl == 101.0 and tgt == 98.0


def test_sl_target_atr_mode_widens_with_volatility():
    df = _ohlc([100 + (i % 2) * 8 for i in range(40)])  # choppy => higher ATR
    cfg = {"sl_mode": "atr", "atr_period": 14, "atr_sl_mult": 1.5, "atr_target_mult": 3.0,
           "stop_loss_pct": 1.0, "target_pct": 2.0}
    sl, tgt = _sl_target(df, 100.0, "BUY", cfg)
    assert sl < 99.0        # ATR stop wider than the 1% fixed stop
    assert tgt > 102.0


def test_sl_target_atr_falls_back_when_no_atr():
    df = _ohlc([100, 101, 102])  # too short for ATR
    cfg = {"sl_mode": "atr", "stop_loss_pct": 1.0, "target_pct": 2.0}
    sl, tgt = _sl_target(df, 100.0, "BUY", cfg)
    assert sl == 99.0 and tgt == 102.0


def test_supertrend_dir_none_when_short():
    assert _supertrend_dir(_ohlc([1, 2, 3]), 10, 3.0) is None


def test_supertrend_dir_tracks_uptrend():
    df = _ohlc([1000 + i * 3 for i in range(40)])   # steady uptrend
    direction = _supertrend_dir(df, 10, 3.0)
    assert direction is not None
    assert direction[-1] == 1


# ── market_regime (SCRUM-67) ─────────────────────────────────────────────────

def _index_df(closes):
    return pd.DataFrame({
        "open": closes, "high": [c + 5 for c in closes],
        "low": [c - 5 for c in closes], "close": closes,
        "volume": [1000] * len(closes),
    })


_REGIME_CFG = {"regime_ema": 20, "regime_band_pct": 0.1}


def test_regime_bullish_when_price_above_ema():
    closes = [22000 + i * 20 for i in range(40)]  # steady uptrend
    assert market_regime(_index_df(closes), _REGIME_CFG) == "BULLISH"


def test_regime_bearish_when_price_below_ema():
    closes = [23000 - i * 20 for i in range(40)]  # steady downtrend
    assert market_regime(_index_df(closes), _REGIME_CFG) == "BEARISH"


def test_regime_neutral_when_flat():
    closes = [22000.0] * 40  # dead flat — close == ema
    assert market_regime(_index_df(closes), _REGIME_CFG) == "NEUTRAL"


def test_regime_neutral_when_insufficient_data():
    closes = [22000 + i * 20 for i in range(10)]  # fewer than ema+5 rows
    assert market_regime(_index_df(closes), _REGIME_CFG) == "NEUTRAL"


def test_regime_neutral_when_df_none():
    assert market_regime(None, _REGIME_CFG) == "NEUTRAL"
