"""Strategy Maker - Monte-Carlo permutation test (report-only edge-vs-noise check)."""
import os
import random

import numpy as np
import pandas as pd
import yaml

from maker.grammar import make_candidate
from maker.permute import permutation_pvalue, permute_ohlc


def _wobble(n=400):
    close = [100 + 20 * np.sin(i / 15) + i * 0.05 for i in range(n)]
    return pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n, freq="D"),
        "open": close, "high": [c + 1 for c in close], "low": [c - 1 for c in close],
        "close": close, "volume": [100000] * n})


def test_permute_preserves_shape_and_anchor_but_changes_path():
    df = _wobble(200)
    out = permute_ohlc(df, random.Random(1))
    assert len(out) == len(df)
    assert out["open"].iloc[0] == df["open"].iloc[0]          # first bar anchored
    assert not np.allclose(out["close"].to_numpy(), df["close"].to_numpy())  # path changed
    assert (out["high"] >= out["low"]).all()                  # still valid bars


def test_permutation_pvalue_is_well_formed():
    cfg = yaml.safe_load(open(os.path.join("config", "config.yaml")))
    cfg["strategy"]["regime_filter_enabled"] = False
    cfg["trading"]["entry_start_time"] = ""; cfg["trading"]["entry_end_time"] = ""
    cfg["costs"]["product"] = "delivery"
    cand = make_candidate("long", {
        "setup": ("nday_extreme", {"lookback": 50, "side": "high"}),
        "trigger": ("breakout_close", {"of": "setup_level"}),
        "exit": ("r_multiple", {"r": 2})})
    res = permutation_pvalue(cand, {"AAA": _wobble(), "BBB": _wobble()}, cfg,
                             n_perms=15, window=120, seed=3)
    assert set(res) == {"permutation_p", "obs_net", "n_perms", "n_ge"}
    assert 0.0 < res["permutation_p"] <= 1.0
    assert res["n_perms"] == 15 and 0 <= res["n_ge"] <= 15
