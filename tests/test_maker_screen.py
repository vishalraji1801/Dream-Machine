"""Strategy Maker — Commit 5: cheap screen kill logic (test 6)."""
import os

import pandas as pd
import yaml

from maker.grammar import make_candidate
from maker.screen import screen_candidate, screen_decision


def test_screen_kills_too_few_trades():
    passed, reason = screen_decision({"trades": 20, "pf": 1.5, "net": 1000, "top3_frac": 0.2})
    assert not passed and reason == "too_few_trades"


def test_screen_kills_low_pf():
    passed, reason = screen_decision({"trades": 60, "pf": 1.05, "net": 1000, "top3_frac": 0.2})
    assert not passed and reason == "low_pf"


def test_screen_kills_net_negative():
    passed, reason = screen_decision({"trades": 60, "pf": 1.5, "net": -50, "top3_frac": 0.2})
    assert not passed and reason == "net_negative"


def test_screen_kills_outlier_carried():
    passed, reason = screen_decision({"trades": 60, "pf": 1.5, "net": 1000, "top3_frac": 0.72})
    assert not passed and reason == "outlier_carried"


def test_screen_passes_clean_candidate():
    passed, reason = screen_decision({"trades": 60, "pf": 1.5, "net": 1000, "top3_frac": 0.30})
    assert passed and reason == "pass"


def test_screen_candidate_runs_end_to_end():
    # integration smoke: compile -> backtest -> metrics, on synthetic candles.
    cfg = yaml.safe_load(open(os.path.join("config", "config.yaml")))
    cfg["strategy"]["regime_filter_enabled"] = False
    cfg["trading"]["entry_start_time"] = ""; cfg["trading"]["entry_end_time"] = ""
    cfg["costs"]["product"] = "delivery"

    def wobble(n=600):
        import math as _m
        close = [100 + 20 * _m.sin(i / 15) + i * 0.05 for i in range(n)]
        return pd.DataFrame({"timestamp": pd.date_range("2018-01-01", periods=n, freq="D"),
                             "open": close, "high": [c + 1 for c in close],
                             "low": [c - 1 for c in close], "close": close,
                             "volume": [100000] * n})
    candles = {"AAA": wobble(), "BBB": wobble()}
    cand = make_candidate("long", {
        "setup": ("nday_extreme", {"lookback": 50, "side": "high"}),
        "trigger": ("breakout_close", {"of": "setup_level"}),
        "exit": ("r_multiple", {"r": 2})})
    passed, reason, m = screen_candidate(cand, candles, cfg, window=120)
    assert isinstance(passed, bool)
    assert set(m) == {"trades", "pf", "net", "top3_frac", "rank"}


def test_screen_applies_slippage_for_intraday_only():
    from maker.screen import _prepare_cfg
    from maker.grammar import make_candidate
    intraday = make_candidate("long", {
        "setup": ("opening_range", {"window_min": 15, "break_side": "high"}),
        "trigger": ("candle_confirm_1m", {"accept": ("hammer_white", "doji"), "above_vwap": True}),
        "exit": ("r_multiple", {"r": 2}),
        "hold": ("square_off", {"at": "15:10"})}, sleeve="intraday")
    swing = make_candidate("long", {
        "setup": ("nday_extreme", {"lookback": 100, "side": "high"}),
        "trigger": ("breakout_close", {"of": "setup_level"}),
        "exit": ("atr_trail", {"mult": 5, "period": 14})}, sleeve="swing")
    ci = _prepare_cfg(intraday, {"costs": {}})
    cs = _prepare_cfg(swing, {"costs": {}})
    assert ci["backtest"]["exec_slippage_pct"] == 0.10          # slippage in the screen
    assert ci["strategy"]["long_only"] is False                 # intraday keeps shorts
    assert "exec_slippage_pct" not in cs.get("backtest", {})    # swing screen: no slippage
    assert cs["strategy"]["long_only"] is True
