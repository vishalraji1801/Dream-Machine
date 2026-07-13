"""Live router integration — regime → active strategies, using real config/seed."""
import yaml
import pandas as pd
import pytest

from src.live_router import LiveRouter
from src.regime import Regime


def _cfg():
    return yaml.safe_load(open("config/config.yaml", encoding="utf-8"))


def _index(closes):
    return pd.DataFrame({"open": closes, "high": [c + 2 for c in closes],
                         "low": [c - 2 for c in closes], "close": closes,
                         "volume": [1_000_000] * len(closes)})


def _uptrend(n=150):
    return _index([1000 + i * 3 for i in range(n)])           # strong steady uptrend


def _rangebound(n=150):
    return _index([1000 + (1 if i % 2 else -1) for i in range(n)])   # tiny oscillation


def test_router_activates_supertrend_in_strong_trend():
    lr = LiveRouter(_cfg(), mode="paper")
    active = lr.step(_uptrend())
    assert lr.regime.regime is Regime.STRONG_TREND_UP
    assert "supertrend" in [a.name for a in active]           # seeded + validated
    assert all(a.weight > 0 for a in active)


def test_router_sits_out_in_range():
    lr = LiveRouter(_cfg(), mode="paper")
    active = lr.step(_rangebound())
    # supertrend is disabled in non-trend regimes -> not active (router trades nothing)
    assert "supertrend" not in [a.name for a in active]


def test_router_persists_and_carries_hysteresis():
    lr = LiveRouter(_cfg(), mode="paper")
    lr.step(_uptrend())
    first = lr.regime
    lr.step(_uptrend())
    assert lr.regime.since_bars >= first.since_bars           # dwell accumulates


def test_signals_for_is_safe_list():
    lr = LiveRouter(_cfg(), mode="paper")
    lr.step(_uptrend())
    # a supertrend flip-up series
    closes = [1000 - i * 6 for i in range(28)] + [1000 - 27 * 6 + 120]
    df = pd.DataFrame({"open": closes, "high": [c + 2 for c in closes],
                       "low": [c - 2 for c in closes], "close": closes,
                       "volume": [500_000] * len(closes)})
    sigs = lr.signals_for("X", df)
    assert isinstance(sigs, list)
    for sig, astrat in sigs:
        assert sig.direction in ("BUY", "SELL")
        assert astrat.name == "supertrend"


def test_no_index_data_trades_nothing():
    lr = LiveRouter(_cfg(), mode="paper")
    assert lr.step(None) == []
    assert lr.step(_index([])) == []


def test_daily_strategies_not_active_intraday():
    # bb/donchian are validated:false -> never active in paper via the router
    lr = LiveRouter(_cfg(), mode="paper")
    lr.step(_uptrend())
    names = [a.name for a in lr.active]
    assert "bb_mean_reversion" not in names
    assert "donchian_trend_tsl" not in names
