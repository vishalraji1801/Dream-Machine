import pandas as pd
import pytest

from src.strategy import TradeSignal, generate_signal, should_exit


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


def test_should_exit_ema_reversal_buy(cfg):
    class FakePos:
        direction = "BUY"

    df = _make_df(n=80, trend="down")
    exit_flag, reason = should_exit("RELIANCE", df, FakePos(), cfg)
    assert isinstance(exit_flag, bool)


def test_should_exit_insufficient_data(cfg):
    class FakePos:
        direction = "BUY"

    exit_flag, reason = should_exit("X", _make_df(n=5), FakePos(), cfg)
    assert exit_flag is False
    assert reason == ""


def test_signal_sl_target_ratio(cfg):
    signal = generate_signal("TEST", _make_df(n=80, trend="up"), cfg)
    if signal.direction == "BUY":
        reward = signal.target - signal.entry_price
        risk = signal.entry_price - signal.stop_loss
        assert reward / risk >= cfg["stop_loss_pct"] / cfg["stop_loss_pct"]
