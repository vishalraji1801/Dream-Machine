"""Strategy Maker — Commit 9: end-to-end campaign funnel (test 10)."""
import math
import os

import pandas as pd
import yaml

from maker.campaign import run_campaign
from maker.generate import random_candidates
from maker.registry import Registry


def _cfg():
    cfg = yaml.safe_load(open(os.path.join("config", "config.yaml")))
    cfg["strategy"]["regime_filter_enabled"] = False
    cfg["trading"]["entry_start_time"] = ""; cfg["trading"]["entry_end_time"] = ""
    cfg["costs"]["product"] = "delivery"
    return cfg


def _wobble(n=800, seed=0):
    close = [100 + 22 * math.sin(i / 13 + seed) + i * 0.04 for i in range(n)]
    return pd.DataFrame({"timestamp": pd.date_range("2016-01-01", periods=n, freq="D"),
                         "open": close, "high": [c + 1 for c in close],
                         "low": [c - 1 for c in close], "close": close,
                         "volume": [100000] * n})


def test_generation_is_seeded_and_within_budget():
    a = random_candidates(10, seed=42)
    b = random_candidates(10, seed=42)
    assert [c.cid for c in a] == [c.cid for c in b]        # deterministic
    for c in a:
        assert c.n_conditions <= 3 and c.n_params <= 4      # parsimony holds


def test_campaign_funnel_counts_consistent(tmp_path):
    reg = Registry(str(tmp_path / "t.db"))
    candles = {"AAA": _wobble(seed=0), "BBB": _wobble(seed=3)}
    counts = run_campaign(15, seed=7, candles=candles, cfg=_cfg(), registry=reg, window=120)

    assert counts["generated"] == 15
    assert counts["generated"] == counts["gen_reject"] + counts["screened"]
    assert counts["screened"] == counts["screen_fail"] + counts["gauntlet_run"]
    # every stage is logged (RULE 1) — registry rows match the funnel counts
    assert reg.count(stage="GEN_REJECT") == counts["gen_reject"]
    assert reg.count(stage="SCREEN") == counts["screened"]
    assert reg.count(stage="GAUNTLET") == counts["gauntlet_run"]
    # N_effective is the distinct families that reached screen+
    assert reg.n_effective() >= 1 if counts["screened"] else True
