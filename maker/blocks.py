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
    sleeves: tuple = ("swing", "intraday")   # which sleeves may use this block

    def __post_init__(self):
        if self.slot not in SLOTS:
            raise ValueError(f"unknown slot {self.slot!r}; must be one of {SLOTS}")
        if not self.rationale or not self.rationale.strip():
            raise ValueError(
                f"block {self.name!r} has no rationale — every block needs an economic story")
        if not self.params:
            raise ValueError(f"block {self.name!r} declares no parameter grid")


def _b(slot, name, params, rationale, sleeves=("swing", "intraday")):
    return Block(slot, name, params, rationale, sleeves)


_IN = ("intraday",)


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
    # ── support/resistance setups (section 15) — tier-1 has no detection params ──
    _b("setup", "objective_level", {"level": ["pdh", "pdl", "pdc", "round"]},
       "Prior-day and round levels are objective S/R the whole market watches; with no "
       "detection parameters they cannot be curve-fit."),
    _b("setup", "pivot_cluster_level", {"touch_min": [2, 3], "swing_n": [5, 10, 20],
                                        "cluster_tol_atr": [0.25, 0.5], "zone_atr": [0.25, 0.5]},
       "Repeated swing-pivot touches mark a real S/R shelf; more and more-recent touches "
       "make it stronger (highest overfitting risk — its params count against the budget)."),
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

    # ═══ INTRADAY JARS (section 11.2) — intraday sleeve only ══════════════════
    # regime (session / stocks-in-play filters)
    _b("regime", "time_window", {"allow": [("09:30", "11:00"), ("11:00", "14:00"),
                                           ("14:00", "15:00")]},
       "Intraday edges are often session-specific; the open behaves differently from midday.", _IN),
    _b("regime", "skip_open_minutes", {"min": [0, 15, 30]},
       "Skipping the first minutes avoids the noisiest, widest-spread part of the session.", _IN),
    _b("regime", "rvol_gate", {"min": [1.5, 3, 5]},
       "Relative volume finds stocks-in-play where intraday moves are large enough to pay.", _IN),
    _b("regime", "scanner_rank", {"top_n": [10, 30]},
       "Trading only scanner-selected names focuses on the day's movers, not a fixed list.", _IN),
    # setup
    _b("setup", "opening_range", {"window_min": [5, 15, 30],
                                  "break_side": ["high", "low", "gap_aligned"]},
       "The opening range frames the day; its break is the most cross-validated intraday setup.", _IN),
    _b("setup", "vwap_relation", {"state": ["reclaim", "break_below", "hold_above"],
                                  "min_dist_pct": [0, 0.3]},
       "VWAP is intraday fair value; reclaims and rejections mark shifts in intraday control.", _IN),
    _b("setup", "intraday_flush", {"down_pct_in_min": [(2, 15), (3, 30)]},
       "A fast intraday flush in a strong name is a liquidity-vacuum overreaction that snaps back.", _IN),
    _b("setup", "prior_day_level", {"level": ["pdh", "pdl", "pdc"], "action": ["break", "reject"]},
       "Prior-day high/low/close are objective levels the whole market watches intraday.", _IN),
    # trigger
    _b("trigger", "candle_confirm_1m", {"accept": [("hammer_white", "doji")], "above_vwap": [True]},
       "A 1-min confirmation candle above VWAP demands buyers show up before intraday entry.", _IN),
    _b("trigger", "new_extreme_after_pullback", {"pullback_bars": [1, 2, 3]},
       "A new extreme after a shallow pullback confirms intraday momentum resumed.", _IN),
    # hold (square_off is MANDATORY for intraday)
    _b("hold", "square_off", {"at": ["15:10"]},
       "MIS positions must close before the exchange auto-square-off; a hard time exit is mandatory.", _IN),
    _b("hold", "max_hold_min", {"max": [30, 60, 120]},
       "A max intraday hold caps time-decay of an idea and forces capital recycling.", _IN),
]

BLOCKS = {b.name: b for b in _LIBRARY}


def blocks_for_slot(slot: str, sleeve: str = None) -> list:
    """Blocks in a slot, optionally filtered to those valid for a sleeve (section 1/11.2)."""
    if slot not in SLOTS:
        raise ValueError(f"unknown slot {slot!r}")
    return [b for b in _LIBRARY if b.slot == slot
            and (sleeve is None or sleeve in b.sleeves)]


def get_block(name: str) -> Block:
    return BLOCKS[name]
