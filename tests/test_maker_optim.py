"""Strategy Maker — Commits 22/25/26: staged screen, budget guard, family reserve guard
(tests 22-subset, 26, 27)."""
import math

import pandas as pd
import pytest
import yaml
import os

from maker.campaign import run_campaign
from maker.grammar import make_candidate
from maker.registry import Registry, family_id
from maker.screen import staged_screen
from maker import reserve as R


def _cfg():
    cfg = yaml.safe_load(open(os.path.join("config", "config.yaml")))
    cfg["strategy"]["regime_filter_enabled"] = False
    cfg["trading"]["entry_start_time"] = ""; cfg["trading"]["entry_end_time"] = ""
    cfg["costs"]["product"] = "delivery"
    return cfg


def _flat(n=400, seed=0):
    close = [100 + 0.001 * i for i in range(n)]           # nearly flat -> almost no breakouts
    return pd.DataFrame({"timestamp": pd.date_range("2018-01-01", periods=n, freq="D"),
                         "open": close, "high": [c + 0.2 for c in close],
                         "low": [c - 0.2 for c in close], "close": close, "volume": [1000] * n})


def _wobble(n=800, seed=0):
    close = [100 + 22 * math.sin(i / 13 + seed) + i * 0.04 for i in range(n)]
    return pd.DataFrame({"timestamp": pd.date_range("2016-01-01", periods=n, freq="D"),
                         "open": close, "high": [c + 1 for c in close],
                         "low": [c - 1 for c in close], "close": close, "volume": [1000] * n})


# ── staged screen pre-check (section 16.3) ───────────────────────────────────

def test_precheck_kills_before_full_run():
    cand = make_candidate("long", {
        "setup": ("nday_extreme", {"lookback": 200, "side": "high"}),
        "trigger": ("breakout_close", {"of": "setup_level"}),
        "exit": ("r_multiple", {"r": 2})})
    candles = {f"S{i}": _flat(seed=i) for i in range(4)}
    passed, reason, m = staged_screen(cand, candles, _cfg(), subset=["S0", "S1"], window=210)
    assert not passed and reason == "precheck_too_few_trades" and m["stage"] == "precheck"


# ── budget guard: no trial without a terminal status (test 26) ────────────────

def test_campaign_leaves_no_ambiguous_trials(tmp_path):
    reg = Registry(str(tmp_path / "t.db"))
    run_campaign(8, seed=3, candles={"A": _wobble(seed=0)}, cfg=_cfg(), registry=reg,
                 window=120, time_budget_s=1e9)
    for row in reg.rows():
        assert row["status"] in ("PASS", "FAIL", "ALIVE", "DEAD")   # always terminal


# ── family reserve guard: one shot per family across TF variants (test 27) ────

def test_reserve_one_shot_across_tf_variants(tmp_path):
    lock = R.write_lock("2023-01-01", ["A"], path=str(tmp_path / "reserve_lock.json"))
    reg = Registry(str(tmp_path / "t.db"))
    blocks = {"setup": ("nday_extreme", {"lookback": 100, "side": "high"}),
              "trigger": ("breakout_close", {"of": "setup_level"}),
              "exit": ("atr_trail", {"mult": 5, "period": 14})}
    df = pd.DataFrame({"timestamp": pd.date_range("2018-01-01", periods=1600, freq="D"),
                       "open": range(1600), "high": range(1600), "low": range(1600),
                       "close": range(1600), "volume": [1] * 1600})
    fake = lambda *a: {"trades": 40, "pf": 1.6, "net": 5000, "top3_frac": 0.2, "rank": 5.0}
    c15 = make_candidate("long", blocks, sleeve="swing", timeframe="1d")
    R.evaluate_once(c15, family_id(c15), {"A": df}, lock, reg, 100, {}, evaluator=fake)
    # a DIFFERENT timeframe variant of the same family gets NO second reserve shot
    c30 = make_candidate("long", blocks, sleeve="swing", timeframe="1w")
    assert c30.cid != c15.cid and family_id(c30) == family_id(c15)
    with pytest.raises(RuntimeError):
        R.evaluate_once(c30, family_id(c30), {"A": df}, lock, reg, 100, {}, evaluator=fake)
