"""Strategy Maker — process-parallel campaign equivalence.

The one guarantee that matters: for the same seed, the parallel campaign writes a registry
BYTE-IDENTICAL to the serial one (same rows, same order, same metrics, same bar) — proving
we broke neither determinism (RULE-free reproducibility) nor RULE 1 (append-only, one
writer, ordered). Everything else about parallelism is a speed detail; this is correctness.
"""
import math
import os

import pandas as pd
import pytest
import yaml

from maker.campaign import run_campaign
from maker.parallel_campaign import run_campaign_parallel
from maker.registry import Registry


def _cfg():
    cfg = yaml.safe_load(open(os.path.join("config", "config.yaml")))
    cfg["strategy"]["regime_filter_enabled"] = False
    cfg["trading"]["entry_start_time"] = ""; cfg["trading"]["entry_end_time"] = ""
    cfg["costs"]["product"] = "delivery"
    return cfg


def _trend(seed, n=700):
    close = [100 + 30 * math.sin(i / 17 + seed) + i * 0.15 for i in range(n)]
    return pd.DataFrame({"timestamp": pd.date_range("2016-01-01", periods=n, freq="D"),
                         "open": close, "high": [c + 2 for c in close],
                         "low": [c - 2 for c in close], "close": close,
                         "volume": [1000] * n})


# the columns that must match; id is autoincrement, created_at is a wall-clock stamp
_COLS = ("cid", "family", "sleeve", "stage", "status", "pf_required", "metrics_json", "notes")


def _sig(reg):
    return [tuple(r[c] for c in _COLS) for r in reg.rows()]


def test_parallel_registry_is_byte_identical_to_serial(tmp_path):
    candles = {f"S{s}": _trend(s) for s in range(4)}
    cfg = _cfg()

    reg_s = Registry(str(tmp_path / "serial.db"))
    counts_s = run_campaign(12, seed=7, candles=candles, cfg=cfg, registry=reg_s)

    reg_p = Registry(str(tmp_path / "parallel.db"))
    counts_p = run_campaign_parallel(12, seed=7, candles=candles, cfg=cfg, registry=reg_p,
                                     workers=4)

    # identical funnel counts (ignore the parallel-only 'workers' key)
    counts_p.pop("workers", None)
    assert counts_s == counts_p
    # identical registry: same rows, same order, same metrics, same bar
    assert _sig(reg_s) == _sig(reg_p)


def test_parallel_is_deterministic_across_worker_counts(tmp_path):
    candles = {f"S{s}": _trend(s) for s in range(4)}
    cfg = _cfg()

    reg1 = Registry(str(tmp_path / "w1.db"))
    run_campaign_parallel(12, seed=7, candles=candles, cfg=cfg, registry=reg1, workers=1)
    reg8 = Registry(str(tmp_path / "w8.db"))
    run_campaign_parallel(12, seed=7, candles=candles, cfg=cfg, registry=reg8, workers=8)

    assert _sig(reg1) == _sig(reg8)   # worker count changes nothing observable


def test_parallel_registry_stays_append_only(tmp_path):
    candles = {f"S{s}": _trend(s) for s in range(3)}
    reg = Registry(str(tmp_path / "p.db"))
    run_campaign_parallel(6, seed=1, candles=candles, cfg=_cfg(), registry=reg, workers=4)
    # RULE 1 enforced at the DB level even though workers ran concurrently
    with pytest.raises(Exception):
        reg._conn.execute("UPDATE trials SET status='HACKED' WHERE id=1")
        reg._conn.commit()
