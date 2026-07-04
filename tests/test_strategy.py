import pandas as pd
import pytest

from src.strategy import TradeSignal, generate_signal


@pytest.fixture
def cfg():
    return {
        "ema_fast": 9,
        "ema_slow": 21,
        "ema_crossover_lookback": 3,
        "rsi_period": 14,
        "rsi_entry_threshold": 60,
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


def test_hold_on_insufficient_data(cfg):
    signal = generate_signal("RELIANCE", _make_df(n=10), cfg)
    assert signal.direction == "HOLD"
    assert signal.reason == "insufficient_data"


def test_returns_trade_signal_instance(cfg):
    signal = generate_signal("RELIANCE", _make_df(n=80), cfg)
    assert isinstance(signal, TradeSignal)
    assert signal.symbol == "RELIANCE"
    assert signal.direction in ("BUY", "SELL", "HOLD")


def test_buy_sl_below_entry(cfg):
    for _ in range(3):
        signal = generate_signal("TEST", _make_df(n=80, trend="up", vol_spike=True), cfg)
        if signal.direction == "BUY":
            assert signal.stop_loss < signal.entry_price
            assert signal.target > signal.entry_price
            assert signal.target > signal.stop_loss
            return
    pytest.skip("No BUY signal generated in this synthetic data")


def test_sell_sl_above_entry(cfg):
    for _ in range(3):
        signal = generate_signal("TEST", _make_df(n=80, trend="down", vol_spike=True), cfg)
        if signal.direction == "SELL":
            assert signal.stop_loss > signal.entry_price
            assert signal.target < signal.entry_price
            return
    pytest.skip("No SELL signal generated in this synthetic data")


def test_hold_returns_zero_prices(cfg):
    signal = generate_signal("RELIANCE", _make_df(n=80), cfg)
    if signal.direction == "HOLD":
        assert signal.entry_price == 0.0
        assert signal.stop_loss == 0.0
        assert signal.target == 0.0


def test_signal_sl_target_ratio(cfg):
    signal = generate_signal("TEST", _make_df(n=80, trend="up"), cfg)
    if signal.direction == "BUY":
        reward = signal.target - signal.entry_price
        risk = signal.entry_price - signal.stop_loss
        assert reward / risk >= cfg["stop_loss_pct"] / cfg["stop_loss_pct"]


# ── market_regime (SCRUM-67) ─────────────────────────────────────────────────

from src.strategy import market_regime


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


# ── V2 P4: ATR helpers, dispatcher, and portfolio strategies ──────────────────

from src.strategy import (STRATEGY_REGISTRY, _atr, _sl_target, _supertrend_dir,
                          generate_signal as gen)


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


# dispatcher

def test_dispatcher_defaults_to_momentum(cfg):
    df = _make_df(n=80, trend="up", vol_spike=True)
    # no 'name' key -> momentum path (may be BUY or HOLD, but must not raise)
    sig = gen("X", df, cfg)
    assert sig.direction in ("BUY", "SELL", "HOLD")


def test_dispatcher_unknown_name_falls_back(cfg):
    cfg = {**cfg, "name": "nonexistent_strategy"}
    sig = gen("X", _make_df(n=80), cfg)
    assert sig.direction in ("BUY", "SELL", "HOLD")


def test_dispatcher_routes_to_named_strategy(cfg):
    calls = {}
    orig = STRATEGY_REGISTRY["vwap_mean_reversion"]
    def spy(symbol, df, c):
        calls["hit"] = True
        return orig(symbol, df, c)
    STRATEGY_REGISTRY["vwap_mean_reversion"] = spy
    try:
        gen("X", _make_df(n=80, trend="down"), {**cfg, "name": "vwap_mean_reversion"})
    finally:
        STRATEGY_REGISTRY["vwap_mean_reversion"] = orig
    assert calls.get("hit")


def test_registry_has_four_strategies():
    assert set(STRATEGY_REGISTRY) == {
        "momentum_vwap_breakout", "vwap_mean_reversion", "orb", "supertrend"}


# vwap mean reversion

def test_vwap_mean_reversion_buys_oversold_below_vwap(cfg):
    c = {**cfg, "name": "vwap_mean_reversion", "vwap_stretch_pct": 0.5,
         "rsi_oversold": 35, "rsi_overbought": 65}
    df = _make_df(n=80, trend="down")  # steady decline => close below vwap, low RSI
    sig = gen("X", df, c)
    assert sig.direction == "BUY"
    assert sig.reason == "vwap_reversion_long"


def test_vwap_mean_reversion_sells_overbought_above_vwap(cfg):
    c = {**cfg, "name": "vwap_mean_reversion", "vwap_stretch_pct": 0.5,
         "rsi_oversold": 35, "rsi_overbought": 65}
    df = _make_df(n=80, trend="up")
    sig = gen("X", df, c)
    assert sig.direction == "SELL"
    assert sig.reason == "vwap_reversion_short"


# supertrend

def test_supertrend_dir_none_when_short():
    assert _supertrend_dir(_ohlc([1, 2, 3]), 10, 3.0) is None


def test_supertrend_flip_up_gives_buy(cfg):
    # long downtrend then a sharp jump on the final candle -> flip to +1
    closes = [1000 - i * 6 for i in range(28)] + [1000 - 27 * 6 + 120]
    highs = [c + 2 for c in closes]
    highs[-1] = closes[-1] + 2
    lows = [c - 2 for c in closes]
    df = _ohlc(closes, highs=highs, lows=lows)
    sig = gen("X", df, {**cfg, "name": "supertrend", "supertrend_period": 10, "supertrend_mult": 3.0})
    assert sig.direction == "BUY"
    assert sig.reason == "supertrend_flip_up"


def test_supertrend_no_flip_holds(cfg):
    df = _ohlc([1000 + i * 3 for i in range(40)])  # steady uptrend, no flip at end
    sig = gen("X", df, {**cfg, "name": "supertrend"})
    assert sig.direction == "HOLD"


# ORB

def test_orb_breaks_opening_range_high(cfg):
    day = "2026-07-06 "
    times, closes, highs, lows, vols = [], [], [], [], []
    # opening range 09:15-09:40 (6 candles) with high ~105
    for i in range(6):
        h, m = 9, 15 + i * 5
        times.append(f"{day}{h:02d}:{m:02d}")
        closes.append(103.0); highs.append(105.0); lows.append(101.0); vols.append(400_000)
    # later candles, last one breaks above 105 with volume
    later = ["09:45", "09:50", "09:55", "10:00", "10:05", "10:10", "10:15", "10:20"]
    for i, hm in enumerate(later):
        times.append(f"{day}{hm}")
        brk = i == len(later) - 1
        closes.append(108.0 if brk else 104.0)
        highs.append(109.0 if brk else 104.5)
        lows.append(103.0)
        vols.append(1_500_000 if brk else 300_000)
    df = _ohlc(closes, vols=vols, highs=highs, lows=lows, timestamps=times)
    c = {**cfg, "name": "orb", "orb_start": "09:15", "orb_end": "09:45",
         "volume_sma_period": 5, "volume_multiplier": 1.5}
    sig = gen("X", df, c)
    assert sig.direction == "BUY"
    assert sig.reason == "orb_break_high"


def test_orb_holds_without_timestamp(cfg):
    sig = gen("X", _make_df(n=40), {**cfg, "name": "orb"})
    assert sig.direction == "HOLD"
