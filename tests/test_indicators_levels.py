"""Pinned indicators — S/R levels, zones, parsimony (spec section 15, tests 21-22)."""
import math

import pandas as pd
import pytest

from indicators.levels import (is_touch, make_zone, pivot_cluster_levels, tier1_levels)
from maker.grammar import make_candidate


def _series(n=120):
    close = [100 + 15 * math.sin(i / 9) + i * 0.05 for i in range(n)]
    return pd.DataFrame({"open": close, "high": [c + 1 for c in close],
                         "low": [c - 1 for c in close], "close": close,
                         "volume": [1000] * n})


# ── test 21: zone semantics + determinism ────────────────────────────────────

def test_zone_touch_semantics():
    z = make_zone(center=100.0, atr_val=4.0, zone_atr=0.25)   # +/- 1.0
    assert z["low"] == 99.0 and z["high"] == 101.0
    assert is_touch(100.5, z) and is_touch(99.0, z)
    assert not is_touch(101.5, z)                             # outside the zone


def test_level_detection_is_deterministic():
    df = _series()
    a = pivot_cluster_levels(df, swing_n=10, as_of=110)
    b = pivot_cluster_levels(df, swing_n=10, as_of=110)
    assert a == b                                            # byte-identical level list


def test_tier1_levels_are_objective():
    df = _series()
    lv = {x["source"] for x in tier1_levels(df, as_of=100)}
    assert {"pdh", "pdl", "pdc", "round"} <= lv


# ── test 22: parsimony accounting for S/R ────────────────────────────────────

def test_pivot_cluster_level_detection_params_count():
    # tier-3 S/R (4 detection params) + a trigger + an exit blows the 4-param budget
    with pytest.raises(ValueError):
        make_candidate("long", {
            "setup": ("pivot_cluster_level", {"touch_min": 2, "swing_n": 10,
                                              "cluster_tol_atr": 0.25, "zone_atr": 0.25}),
            "trigger": ("breakout_close", {"of": "setup_level"}),
            "exit": ("r_multiple", {"r": 2})})


def test_tier1_objective_level_constructs():
    # the tier-1 version of the same idea has no detection params -> fits the budget
    c = make_candidate("long", {
        "setup": ("objective_level", {"level": "pdh"}),
        "trigger": ("breakout_close", {"of": "setup_level"}),
        "exit": ("r_multiple", {"r": 2})})
    assert c.n_params <= 4
