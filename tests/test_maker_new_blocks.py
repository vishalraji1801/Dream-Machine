"""Strategy Maker — ADX + objective S/R blocks wired into the generator.

Guards: both new blocks compile and EVALUATE (no NotImplementedError), adx_band only ever
draws a valid band (min < max), and the generator actually emits both over many draws.
"""
import math

import pandas as pd

from maker.blocks import BLOCKS
from maker.generate import _sample_block, random_candidates
from maker.grammar import compile, make_candidate


def _df(n=300):
    close = [100 + 20 * math.sin(i / 13) + i * 0.05 for i in range(n)]
    return pd.DataFrame({"timestamp": pd.date_range("2016-01-01", periods=n, freq="D"),
                         "open": close, "high": [c + 2 for c in close],
                         "low": [c - 2 for c in close], "close": close, "volume": [1000] * n})


def test_adx_band_compiles_and_evaluates():
    c = make_candidate("long", {
        "regime": ("adx_band", {"min": 20, "max": 100}),
        "setup": ("objective_level", {"level": "pdh"}),
        "trigger": ("breakout_close", {"of": "setup_level"}),
        "exit": ("opposite_band", {"bollinger": (20, 2.0)})})
    assert c.n_params <= 4
    sig = compile(c)("X", _df(), {})          # must not raise NotImplementedError
    assert sig.direction in ("BUY", "HOLD")


def test_objective_level_all_variants_evaluate():
    for lvl in ("pdh", "pdl", "pdc", "round"):
        c = make_candidate("long", {
            "setup": ("objective_level", {"level": lvl}),
            "trigger": ("breakout_close", {"of": "setup_level"}),
            "exit": ("atr_trail", {"mult": 4, "period": 14})})
        sig = compile(c)("X", _df(), {})
        assert sig.direction in ("BUY", "HOLD")


def test_adx_band_sampling_is_always_a_valid_band():
    import random
    rng = random.Random(0)
    for _ in range(200):
        p = _sample_block(rng, BLOCKS["adx_band"])
        assert p["min"] < p["max"]            # never an empty/inverted band


def test_generator_emits_the_new_blocks():
    used = {}
    for c in random_candidates(400, seed=1):
        for bi in c.blocks.values():
            used[bi.name] = used.get(bi.name, 0) + 1
    assert used.get("objective_level", 0) > 0
    assert used.get("adx_band", 0) > 0        # rarer (2 params) but present
