"""Commit 9 — whole-router backtest vs baselines (deliverable 9)."""
import pandas as pd

from src.regime import RegimeConfig
from src.router import PremarketAllocation, RouterConfig
from src.router_backtest import (format_comparison, regime_timeline, run_comparison)
from src.strategy_meta import load_strategy_meta


def _df(closes):
    return pd.DataFrame({"open": closes, "high": [c + 1 for c in closes],
                         "low": [c - 1 for c in closes], "close": closes,
                         "volume": [100_000] * len(closes)})


def _trend_up_signal(sub):
    # BUY while the last close is above the close 10 bars back (momentum)
    if len(sub) < 11:
        return "HOLD"
    return "BUY" if sub["close"].iloc[-1] > sub["close"].iloc[-11] else "SELL"


def _meta(name, pf_up=1.8):
    return load_strategy_meta({
        "name": name,
        "regime_param_sets": {"STRONG_TREND_UP": {"validated": True},
                              "default": {"validated": True}},
        "regime_fit": {"STRONG_TREND_UP": {"pf": pf_up, "trades": 100}},
    })


def test_regime_timeline_length_and_no_lookahead():
    df = _df([100 + i for i in range(90)])
    tl = regime_timeline(df, RegimeConfig(min_bars=40), {"ms_ema_slow": 30})
    assert len(tl) == len(df)
    # state at bar i must not depend on bars after i: recompute a prefix independently
    tl_prefix = regime_timeline(df.iloc[:60], RegimeConfig(min_bars=40), {"ms_ema_slow": 30})
    assert tl[59].regime == tl_prefix[59].regime


def test_comparison_structure_and_report():
    df = _df([100 + i * 0.5 for i in range(120)])          # steady uptrend
    metas = [_meta("mom")]
    fns = {"mom": _trend_up_signal}
    res = run_comparison(df, metas, fns, RegimeConfig(min_bars=40),
                         RouterConfig(mode="backtest"), PremarketAllocation(1.0),
                         window=30, ms_cfg={"ms_ema_slow": 30})
    assert set(res) >= {"routed", "best_single", "equal_weight",
                        "routed_beats_best_single", "routed_beats_equal_weight"}
    assert "mom" in res["singles"]
    report = format_comparison(res)
    assert "REGIME ROUTER" in report and "Verdict" in report


def test_routing_gates_by_regime():
    # a strategy only validated+fit in STRONG_TREND_UP should trade in the routed
    # run only while that regime holds -> routed net differs from always-on single
    df = _df([100 + i * 0.5 for i in range(120)])
    res = run_comparison(df, [_meta("mom")], {"mom": _trend_up_signal},
                         RegimeConfig(min_bars=40), RouterConfig(mode="backtest"),
                         PremarketAllocation(1.0), window=30, ms_cfg={"ms_ema_slow": 30})
    # routed is gated/weighted, single is ungated -> not identical in general
    assert res["routed"] != res["best_single"] or res["best_single"] == 0.0


def test_empty_registry_trades_nothing():
    df = _df([100 + i for i in range(80)])
    res = run_comparison(df, [], {}, RegimeConfig(min_bars=40),
                         RouterConfig(mode="live"), PremarketAllocation(1.0),
                         window=30, ms_cfg={"ms_ema_slow": 30})
    assert res["routed"] == 0.0 and res["best_single"] == 0.0
