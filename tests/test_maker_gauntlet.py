"""Strategy Maker — Commit 7: gauntlet wiring + trial-adjusted bar."""
import math
import os

import pandas as pd
import yaml

from maker.grammar import make_candidate
from maker.registry import Registry, family_id
from maker.run_gauntlet import run_gauntlet, tunable_axes, variants


def _cfg():
    cfg = yaml.safe_load(open(os.path.join("config", "config.yaml")))
    cfg["strategy"]["regime_filter_enabled"] = False
    cfg["trading"]["entry_start_time"] = ""; cfg["trading"]["entry_end_time"] = ""
    cfg["costs"]["product"] = "delivery"
    return cfg


def _wobble(n=900, seed=0):
    close = [100 + 25 * math.sin(i / 12 + seed) + i * 0.03 for i in range(n)]
    return pd.DataFrame({"timestamp": pd.date_range("2016-01-01", periods=n, freq="D"),
                         "open": close, "high": [c + 1 for c in close],
                         "low": [c - 1 for c in close], "close": close,
                         "volume": [100000] * n})


def _cand():
    return make_candidate("long", {
        "setup": ("nday_extreme", {"lookback": 100, "side": "high"}),
        "trigger": ("breakout_close", {"of": "setup_level"}),
        "exit": ("atr_trail", {"mult": 5, "period": 14})})


def test_tunable_axes_and_variants():
    c = _cand()
    axes = tunable_axes(c)
    names = {a[2] for a in axes}
    assert names == {"lookback", "side", "of", "mult"}    # period:[14] excluded (fixed)
    vs = variants(c, cap=24)
    assert 1 < len(vs) <= 24
    assert all(v.direction == "long" for v in vs)


def test_gauntlet_runs_and_records_with_the_bar(tmp_path):
    reg = Registry(str(tmp_path / "trials.db"))
    c = _cand()
    candles = {"AAA": _wobble(seed=0), "BBB": _wobble(seed=1)}
    passed, best, metrics = run_gauntlet(c, candles, _cfg(), reg, family_id(c),
                                         n_effective=100, window=120)
    assert isinstance(passed, bool)
    assert set(metrics) >= {"oos_pf", "oos_trades", "oos_net", "plateau", "best_params"}
    row = reg.rows()[0]
    assert row["stage"] == "GAUNTLET"
    assert row["pf_required"] == 1.35                     # bar for N=100
