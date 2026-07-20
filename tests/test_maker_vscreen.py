"""Strategy Maker — Commit 23: vectorized screen conservatism (test 24)."""
import math
import os

import pandas as pd
import pytest
import yaml

from maker.grammar import make_candidate
from maker.screen import screen_candidate
from maker.vscreen import assert_conservative, vectorized_breakout_pf


def _cfg():
    cfg = yaml.safe_load(open(os.path.join("config", "config.yaml")))
    cfg["strategy"]["regime_filter_enabled"] = False
    cfg["trading"]["entry_start_time"] = ""; cfg["trading"]["entry_end_time"] = ""
    cfg["costs"]["product"] = "delivery"
    return cfg


def _fx(seed, n=900):
    close = [100 + 20 * math.sin(i / (11 + seed)) + i * 0.05 for i in range(n)]
    return pd.DataFrame({"timestamp": pd.date_range("2016-01-01", periods=n, freq="D"),
                         "open": close, "high": [c + 1.5 for c in close],
                         "low": [c - 1.5 for c in close], "close": close, "volume": [1000] * n})


def test_assert_conservative_logic():
    assert assert_conservative(1.2, 1.5)
    assert assert_conservative(1.5, 1.5)
    assert not assert_conservative(1.6, 1.5)


@pytest.mark.parametrize("seed,lookback,r", [(0, 50, 2), (1, 100, 2), (2, 50, 3)])
def test_vectorized_pf_never_exceeds_replay(seed, lookback, r):
    df = _fx(seed)
    vec = vectorized_breakout_pf(df, lookback=lookback, r_mult=r)["pf"]
    cand = make_candidate("long", {
        "setup": ("nday_extreme", {"lookback": lookback, "side": "high"}),
        "trigger": ("breakout_close", {"of": "setup_level"}),
        "exit": ("r_multiple", {"r": r})})
    _, _, m = screen_candidate(cand, {"X": df}, _cfg(), window=max(lookback + 20, 160))
    if m["trades"] < 5:
        pytest.skip("not a calibration fixture — replay produced too few trades")
    replay = m["pf"]
    # the vectorized screen must be conservative — it may only understate the edge
    assert assert_conservative(vec, replay), f"vec {vec} > replay {replay}"
