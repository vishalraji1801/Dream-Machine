"""maker/blocks.py — the block library (Strategy Maker, spec section 1).

Each Block is a pure, parameterized building block over a daily OHLCV frame (+
MarketState where noted). Blocks declare the ONLY parameter values the generator may
ever sample. Every block must carry a non-empty economic rationale — a block whose
story is "the lines cross" does not enter the library.
"""
from dataclasses import dataclass

# The six candidate slots. regime/setup/trigger are the "condition" slots that count
# against RULE 3's max-3-conditions budget (universe/exit/hold do not).
SLOTS = ("universe", "regime", "setup", "trigger", "exit", "hold")
CONDITION_SLOTS = ("regime", "setup", "trigger")


@dataclass(frozen=True)
class Block:
    slot: str
    name: str
    params: dict          # param_name -> list of allowed values (the ONLY values used)
    rationale: str        # one-sentence economic story (required, non-empty)

    def __post_init__(self):
        if self.slot not in SLOTS:
            raise ValueError(f"unknown slot {self.slot!r}; must be one of {SLOTS}")
        if not self.rationale or not self.rationale.strip():
            raise ValueError(
                f"block {self.name!r} has no rationale — every block needs an economic story")
        if not self.params:
            raise ValueError(f"block {self.name!r} declares no parameter grid")


def _b(slot, name, params, rationale):
    return Block(slot, name, params, rationale)


_LIBRARY = [
    # ── universe ────────────────────────────────────────────────────────────
    _b("universe", "liquidity_floor", {"min_turnover_cr": [25, 50]},
       "Illiquid names have wide spreads and unfillable stops; a turnover floor keeps "
       "fills realistic."),
    _b("universe", "price_band", {"band": [(100, 5000)]},
       "Penny stocks and ultra-high-priced names distort sizing and slippage; a price "
       "band keeps the tradeable set sane."),
    # ── regime ──────────────────────────────────────────────────────────────
    _b("regime", "trend_side", {"ma": [100, 200], "side": ["above", "below"]},
       "A long-term MA separates uptrends from downtrends; most edges are "
       "regime-conditional, not all-weather."),
    _b("regime", "adx_band", {"min": [0, 20, 25], "max": [20, 25, 100]},
       "ADX gates trend vs range: breakouts pay in high-ADX, mean-reversion in low-ADX."),
    _b("regime", "bb_width_pctile", {"below": [15, 25], "above": [75, 85]},
       "Bollinger-width percentile marks coiled (low) vs extended (high) volatility "
       "states that precede expansion or reversion."),
    # ── setup ───────────────────────────────────────────────────────────────
    _b("setup", "nday_extreme", {"lookback": [50, 100, 150, 200], "side": ["high", "low"]},
       "A new N-day extreme is the classic trend-continuation footprint (Donchian)."),
    _b("setup", "pullback_depth", {"from_high_pct": [5, 10, 15], "within_trend_ma": [200]},
       "Buying a measured pullback inside an uptrend enters strength at a discount."),
    _b("setup", "compression", {"bbw_pctile_below": [10, 15, 25], "min_bars": [5, 10]},
       "Volatility contraction precedes expansion; a squeeze marks stored energy."),
    _b("setup", "flush", {"down_pct_in_bars": [(7, 3), (10, 5), (15, 5)]},
       "A sharp multi-bar flush in a strong name is a liquidity-vacuum overreaction that "
       "often snaps back."),
    _b("setup", "gap", {"gap_pct_min": [2, 3, 5], "direction": ["up", "down"]},
       "A gap marks an overnight information shock; continuation or fade depends on "
       "context."),
    _b("setup", "band_touch", {"bollinger": [(20, 2.0), (20, 2.5)], "side": ["lower", "upper"]},
       "A close beyond a Bollinger band is a statistical stretch that tends to revert "
       "within a trend."),
    # ── trigger ─────────────────────────────────────────────────────────────
    _b("trigger", "breakout_close", {"of": ["setup_level", "prior_day_high", "prior_day_low"]},
       "Requiring a close beyond the level filters intrabar fake-outs."),
    _b("trigger", "limit_below", {"offset_pct": [0, 2, 3, 5]},
       "A limit below market buys the pullback at a defined price instead of chasing."),
    _b("trigger", "confirm_candle", {"accept": [("hammer_white", "doji")], "above_vwap": [True]},
       "A confirmation candle above VWAP demands the buyers show up before entry."),
    _b("trigger", "resume_new_high", {"within_bars": [3, 5]},
       "Entering only when price resumes to a new high confirms the pullback is over."),
    # ── exit ────────────────────────────────────────────────────────────────
    _b("exit", "atr_trail", {"mult": [3, 4, 5, 6], "period": [14]},
       "An ATR trailing stop lets a trend run while adapting the stop to volatility."),
    _b("exit", "r_multiple", {"r": [1.5, 2, 3]},
       "A fixed R-multiple target books a defined reward against the entry risk."),
    _b("exit", "opposite_band", {"bollinger": [(20, 2.0)]},
       "Exiting at the opposite band captures a mean-reversion move back to fair value."),
    _b("exit", "ma_cross_exit", {"ma": [20, 50]},
       "A close back through a moving average signals the move has stalled."),
    # ── hold ────────────────────────────────────────────────────────────────
    _b("hold", "time_stop", {"max_days": [10, 20, 40]},
       "A time stop frees capital from trades that stop working without hitting a stop."),
    _b("hold", "min_expected_hold", {"min_days": [3, 5]},
       "A minimum expected hold enforces the turnover budget so delivery costs are "
       "amortized over enough move."),
]

BLOCKS = {b.name: b for b in _LIBRARY}


def blocks_for_slot(slot: str) -> list:
    """All blocks in a slot (spec section 1)."""
    if slot not in SLOTS:
        raise ValueError(f"unknown slot {slot!r}")
    return [b for b in _LIBRARY if b.slot == slot]


def get_block(name: str) -> Block:
    return BLOCKS[name]
