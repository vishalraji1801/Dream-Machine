"""maker/generate.py — candidate generation (Strategy Maker, spec section 2).

Seeded random sampling over the block grammar. Only IMPLEMENTED blocks are emitted
(those whose grammar evaluator exists), so every generated candidate compiles and
runs; the whitelist grows as more indicators are pinned. make_candidate enforces the
parsimony budget, so over-budget draws are retried rather than emitted.
"""
import random

from maker.blocks import BLOCKS
from maker.grammar import make_candidate

# blocks with a working evaluator in grammar.compile (expanded as indicators land)
IMPLEMENTED = {
    "regime": ["trend_side", "bb_width_pctile", "adx_band"],
    "setup": ["nday_extreme", "compression", "band_touch", "objective_level"],
    "trigger": ["breakout_close", "limit_below", "resume_new_high"],
    "exit": ["atr_trail", "r_multiple", "opposite_band"],
}


def _sample_block(rng: random.Random, block) -> dict:
    if block.name == "bb_width_pctile":                  # uses exactly ONE side
        side = rng.choice(["below", "above"])
        return {side: rng.choice(block.params[side])}
    if block.name == "adx_band":                         # draw a VALID band (min < max)
        lo = rng.choice(block.params["min"])
        hi = rng.choice([v for v in block.params["max"] if v > lo])
        return {"min": lo, "max": hi}
    return {p: rng.choice(vals) for p, vals in block.params.items()}


def random_candidate(rng: random.Random, direction: str = "long", max_tries: int = 30):
    for _ in range(max_tries):
        pick = {}
        for slot in ("setup", "trigger", "exit"):
            name = rng.choice(IMPLEMENTED[slot])
            pick[slot] = (name, _sample_block(rng, BLOCKS[name]))
        if rng.random() < 0.35:                          # optional regime gate
            name = rng.choice(IMPLEMENTED["regime"])
            pick["regime"] = (name, _sample_block(rng, BLOCKS[name]))
        try:
            return make_candidate(direction, pick)       # raises if over the budget
        except ValueError:
            continue
    # guaranteed within-budget fallback
    return make_candidate(direction, {
        "setup": ("compression", _sample_block(rng, BLOCKS["compression"])),
        "trigger": ("limit_below", {"offset_pct": rng.choice([0, 2, 3, 5])}),
        "exit": ("opposite_band", {"bollinger": (20, 2.0)})})


def random_candidates(n: int, seed: int = 0, direction: str = "long"):
    rng = random.Random(seed)
    return [random_candidate(rng, direction) for _ in range(n)]
