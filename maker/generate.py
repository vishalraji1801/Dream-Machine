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
# Candlestick/chart-pattern catalog ENABLED:
#   chart setups   : pullback_depth, flush, gap, double_bottom, inv_head_shoulders, fib_pullback
#   candlestick trg: confirm_candle (hammer/doji), bullish_reversal_candle (engulfing/morning_star)
IMPLEMENTED = {
    "regime": ["trend_side", "bb_width_pctile", "adx_band"],
    "setup": ["nday_extreme", "compression", "band_touch", "objective_level",
              "pullback_depth", "flush", "gap", "double_bottom",
              "inv_head_shoulders", "fib_pullback"],
    "trigger": ["breakout_close", "limit_below", "resume_new_high",
                "confirm_candle", "bullish_reversal_candle"],
    "exit": ["atr_trail", "r_multiple", "opposite_band"],
}

# Intraday sleeve (section 11.2): session-relative blocks with working evaluators. square_off
# is added to every candidate (mandatory MIS exit). rvol_gate/scanner_rank (cross-sectional)
# and max_hold_min (needs a backtester max-hold exit) are deferred. v1 is LONG-ONLY: the
# trigger/setup semantics are long-oriented, so shorts are a follow-up.
IMPLEMENTED_INTRADAY = {
    "regime": ["time_window", "skip_open_minutes"],
    "setup": ["opening_range", "vwap_relation", "prior_day_level", "intraday_flush"],
    "trigger": ["breakout_close", "limit_below", "candle_confirm_1m",
                "new_extreme_after_pullback"],
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


def random_candidate(rng: random.Random, direction: str = "long", max_tries: int = 30,
                     sleeve: str = "swing", timeframe: str = None):
    if sleeve == "intraday":
        return _random_intraday(rng, direction, max_tries, timeframe)
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


def _random_intraday(rng: random.Random, direction: str, max_tries: int, timeframe: str = None):
    """Intraday candidate: a MANDATORY session/stocks-in-play regime gate (time_window or
    skip_open_minutes — constraints reject an all-day fixed-list candidate as the already-
    falsified region) + the mandatory square_off MIS exit. `timeframe` stamps the candidate
    (5min/15min/…) so the same structure on different bars is a distinct candidate."""
    impl = IMPLEMENTED_INTRADAY
    for _ in range(max_tries):
        rname = rng.choice(impl["regime"])       # always present: keeps it out of the
        pick = {"hold": ("square_off", {"at": "15:10"}),   # proven-dead all-day territory
                "regime": (rname, _sample_block(rng, BLOCKS[rname]))}
        for slot in ("setup", "trigger", "exit"):
            name = rng.choice(impl[slot])
            pick[slot] = (name, _sample_block(rng, BLOCKS[name]))
        try:
            return make_candidate(direction, pick, sleeve="intraday", timeframe=timeframe)
        except ValueError:
            continue
    return make_candidate(direction, {                   # within-budget, admissible fallback
        "regime": ("skip_open_minutes", {"min": 15}),
        "setup": ("opening_range", {"window_min": 15, "break_side": "high"}),
        "trigger": ("breakout_close", {"of": "setup_level"}),
        "exit": ("r_multiple", {"r": 2}),
        "hold": ("square_off", {"at": "15:10"})}, sleeve="intraday", timeframe=timeframe)


def random_candidates(n: int, seed: int = 0, direction: str = "long", sleeve: str = "swing"):
    rng = random.Random(seed)
    return [random_candidate(rng, direction, sleeve=sleeve) for _ in range(n)]
