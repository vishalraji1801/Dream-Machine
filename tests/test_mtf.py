import pandas as pd
import pytest

from src.strategy import generate_signal, higher_tf_trend, TradeSignal
from src.mtf_replay import aggregate_vetoes, replay_outcome, format_report


def _series(closes, start="2026-07-09 09:15", tz="Asia/Kolkata"):
    n = len(closes)
    return pd.DataFrame({
        "timestamp": pd.date_range(start, periods=n, freq="15min", tz=tz),
        "open": closes, "high": [c + 1 for c in closes],
        "low": [c - 1 for c in closes], "close": closes, "volume": [1000] * n,
    })


# ── higher_tf_trend ───────────────────────────────────────────────────────────

def test_higher_tf_trend_up():
    df = _series([100 + i for i in range(220)])          # steady rise
    assert higher_tf_trend(_resample(df), {"rule": "ema_trend", "ema": 50}) == "UP"


def test_higher_tf_trend_down():
    df = _series([300 - i for i in range(220)])
    assert higher_tf_trend(_resample(df), {"rule": "ema_trend", "ema": 50}) == "DOWN"


def test_higher_tf_trend_none_when_short():
    df = _series([100, 101, 102])
    assert higher_tf_trend(_resample(df), {"rule": "ema_trend", "ema": 50}) is None


def _resample(df):
    from src.timeframe import resample_ohlcv
    return resample_ohlcv(df, "1hr")


# ── gate integration via generate_signal ──────────────────────────────────────

def _cfg(**over):
    base = {"name": "always_buy", "mtf_confirm": {"enabled": True, "higher_tf": "1hr",
            "rule": "ema_trend", "ema": 50}}
    base.update(over)
    return base


def test_gate_vetoes_buy_against_downtrend(monkeypatch):
    from src import strategy
    monkeypatch.setitem(strategy.STRATEGY_REGISTRY, "always_buy",
                        lambda s, df, c: TradeSignal("BUY", s, 100.0, 99.0, 102.0, "t"))
    df = _series([300 - i for i in range(220)])          # 1hr trend DOWN
    sig = generate_signal("X", df, _cfg())
    assert sig.direction == "HOLD"
    assert sig.reason.startswith("mtf_veto")
    assert sig.entry_price == 100.0                       # carries signal for replay


def test_gate_passes_buy_with_uptrend(monkeypatch):
    from src import strategy
    monkeypatch.setitem(strategy.STRATEGY_REGISTRY, "always_buy",
                        lambda s, df, c: TradeSignal("BUY", s, 100.0, 99.0, 102.0, "t"))
    df = _series([100 + i for i in range(220)])          # 1hr trend UP
    sig = generate_signal("X", df, _cfg())
    assert sig.direction == "BUY"


def test_gate_fail_closed_while_warming(monkeypatch):
    from src import strategy
    monkeypatch.setitem(strategy.STRATEGY_REGISTRY, "always_buy",
                        lambda s, df, c: TradeSignal("BUY", s, 100.0, 99.0, 102.0, "t"))
    df = _series([100 + i for i in range(20)])           # too few 1hr bars
    sig = generate_signal("X", df, _cfg())
    assert sig.direction == "HOLD" and sig.reason == "mtf_not_ready"


def test_flat_keys_override_nested(monkeypatch):
    from src import strategy
    monkeypatch.setitem(strategy.STRATEGY_REGISTRY, "always_buy",
                        lambda s, df, c: TradeSignal("BUY", s, 100.0, 99.0, 102.0, "t"))
    df = _series([100 + i for i in range(220)])
    # nested disabled, flat enables -> gate active (and passes uptrend)
    cfg = {"name": "always_buy", "mtf_confirm": {"enabled": False},
           "mtf_enabled": True, "mtf_higher_tf": "1hr", "mtf_rule": "ema_trend", "ema": 50}
    assert generate_signal("X", df, cfg).direction == "BUY"


def test_disabled_gate_is_passthrough(monkeypatch):
    from src import strategy
    monkeypatch.setitem(strategy.STRATEGY_REGISTRY, "always_buy",
                        lambda s, df, c: TradeSignal("BUY", s, 100.0, 99.0, 102.0, "t"))
    df = _series([300 - i for i in range(220)])          # downtrend, but gate off
    assert generate_signal("X", df, {"name": "always_buy"}).direction == "BUY"


# ── counterfactual replay ─────────────────────────────────────────────────────

def _future(highs_lows):
    return pd.DataFrame({"high": [h for h, _ in highs_lows], "low": [l for _, l in highs_lows],
                         "open": [h for h, _ in highs_lows], "close": [l for _, l in highs_lows],
                         "volume": [1] * len(highs_lows)})


def test_replay_buy_hits_target():
    out = replay_outcome("BUY", 100, 99, 102, _future([(101, 100), (103, 101)]))
    assert out["outcome"] == "target" and out["pnl_per_share"] == 2.0


def test_replay_buy_hits_sl():
    out = replay_outcome("BUY", 100, 99, 102, _future([(100.5, 98.5)]))
    assert out["outcome"] == "sl" and out["pnl_per_share"] == -1.0


def test_replay_sl_priority_same_bar():
    out = replay_outcome("BUY", 100, 99, 102, _future([(103, 98)]))  # both in one bar
    assert out["outcome"] == "sl"


def test_aggregate_verdict():
    replays = [{"outcome": "sl", "pnl_per_share": -50}, {"outcome": "sl", "pnl_per_share": -30},
               {"outcome": "target", "pnl_per_share": 40}]
    agg = aggregate_vetoes(replays)
    assert agg["avoided_loss"] == 80 and agg["forfeited_win"] == 40
    assert agg["net_benefit"] == 40                       # gate helped
    assert "HELPED" in format_report(agg)
