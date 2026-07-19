"""maker/screen.py — the cheap screen (Strategy Maker, spec section 5).

One fast single-pass in-sample backtest per candidate on the SCREEN span (never the
reserve), full costs. Kills ~90% of candidates in seconds:
  - trades < 30, PF < 1.1, or net <= 0;
  - > 60% of net P&L from the top 3 trades (outlier-carried, not an edge).
Survivors are ranked PF * log(trades) for the gauntlet queue.
"""
import copy
import math

from maker.grammar import compile

DEFAULTS = {"min_trades": 30, "min_pf": 1.1, "top3_max_frac": 0.60}

# A swing/delivery strategy that trades a name more than ~weekly is degenerate — usually a
# tautological "enter every bar" combo. Killing it at the cheap screen (before the
# 24-variant gauntlet) bounds compute and keeps the funnel honest. Deliberately loose
# (~50/name/yr = near-daily) so it only ever catches genuine runaways, not active edges.
OVERTRADE_PER_SYMBOL_YEAR = 50
_TRADING_DAYS = 252

# The compiled candidate fn (grammar.compile) needs >=210 bars of warmup (200-period
# SMA/lookback blocks) or it holds forever. The backtester feeds it a rolling window of
# exactly this many bars, so the maker's screen/gauntlet/reserve MUST run >= that floor —
# below it every candidate produces 0 trades and the whole funnel is silently dead.
WINDOW = 220


def screen_decision(m: dict, thresholds: dict = DEFAULTS) -> tuple[bool, str]:
    """Pure kill logic over computed metrics — the auditable core of the screen."""
    if m["trades"] < thresholds["min_trades"]:
        return False, "too_few_trades"
    if m["pf"] < thresholds["min_pf"]:
        return False, "low_pf"
    if m["net"] <= 0:
        return False, "net_negative"
    if m["top3_frac"] > thresholds["top3_max_frac"]:
        return False, "outlier_carried"
    return True, "pass"


def _metrics(res) -> dict:
    trades, net = res.total_trades, res.net_pnl
    pnls = sorted((t.pnl for t in res.trades), reverse=True)
    top3 = sum(pnls[:3])
    top3_frac = (top3 / net) if net > 0 else 1.0
    pf = res.profit_factor if res.profit_factor != float("inf") else 3.0
    return {"trades": trades, "pf": round(pf, 3), "net": round(net, 2),
            "top3_frac": round(top3_frac, 3),
            "rank": round(pf * math.log(max(trades, 1)), 3)}


def _prepare_cfg(candidate, cfg: dict) -> dict:
    """Sleeve-aware backtest cfg for a candidate. Swing (CNC) is long-only; intraday
    (MIS) keeps both sides AND applies 0.10% execution slippage IN THE SCREEN — prior
    evidence says slippage is where intraday dies, so test it first, not last."""
    c = copy.deepcopy(cfg)
    c.setdefault("strategy", {})["name"] = candidate.cid
    product = str(getattr(candidate, "product", None)
                  or c.get("costs", {}).get("product", "delivery")).lower()
    c.setdefault("costs", {})["product"] = product
    c["strategy"]["long_only"] = product in ("delivery", "cnc")
    if product in ("intraday", "mis"):
        c.setdefault("backtest", {})["exec_slippage_pct"] = 0.10
    return c


def staged_screen(candidate, candles: dict, cfg: dict, subset: list, window: int = WINDOW,
                  thresholds: dict = DEFAULTS, min_precheck_trades: int = 10):
    """Stage 0: a trade-count pre-check on a small representative subset. A candidate
    that can't produce even a handful of trades there won't on the full universe — kill
    it before the full store is touched (section 16.3). Survivors go to the full screen."""
    subset_candles = {s: candles[s] for s in subset if s in candles}
    if subset_candles:
        _, _, m0 = screen_candidate(candidate, subset_candles, cfg, window=window,
                                    thresholds=thresholds)
        if m0["trades"] < min_precheck_trades:
            return False, "precheck_too_few_trades", {"stage": "precheck", **m0}
    passed, reason, m = screen_candidate(candidate, candles, cfg, window=window,
                                         thresholds=thresholds)
    return passed, reason, {"stage": "full", **m}


def screen_candidate(candidate, candles: dict, cfg: dict, window: int = WINDOW,
                     thresholds: dict = DEFAULTS) -> tuple[bool, str, dict]:
    """Compile, run one in-sample backtest, apply the kill logic. Registers the
    compiled fn under the cid only for the duration of the run."""
    from src.backtester import Backtester
    from src.strategy import STRATEGY_REGISTRY
    fn = compile(candidate)
    STRATEGY_REGISTRY[candidate.cid] = fn
    try:
        res = Backtester(_prepare_cfg(candidate, cfg), window=window).run(candles)
    finally:
        STRATEGY_REGISTRY.pop(candidate.cid, None)
    m = _metrics(res)
    # degenerate over-trading guard: bounds compute for pathological recipes and kills
    # tautological combos cheaply, before the expensive gauntlet variant sweep.
    n_sym = max(len(candles), 1)
    years = max((len(df) for df in candles.values()), default=_TRADING_DAYS) / _TRADING_DAYS
    if m["trades"] > OVERTRADE_PER_SYMBOL_YEAR * n_sym * years:
        return False, "overtrading", m
    passed, reason = screen_decision(m, thresholds)
    return passed, reason, m


def _vectorizable(candidate) -> dict:
    """Return {lookback, r_mult} if the candidate is the numpy-vectorizable breakout
    family (long, no regime gate, nday_extreme-high -> breakout_close -> r_multiple),
    else None. Only this shape has a proven conservative vectorized path (vscreen)."""
    if candidate.direction != "long":
        return None
    if candidate.blocks.get("regime") is not None:        # vscreen models no regime gate
        return None
    setup = candidate.blocks.get("setup")
    trigger = candidate.blocks.get("trigger")
    exit_b = candidate.blocks.get("exit")
    if not (setup and trigger and exit_b):
        return None
    if setup.name != "nday_extreme" or setup.params.get("side") != "high":
        return None
    if trigger.name != "breakout_close" or exit_b.name != "r_multiple":
        return None
    return {"lookback": setup.params["lookback"], "r_mult": exit_b.params["r"]}


def fast_screen_candidate(candidate, candles: dict, cfg: dict, window: int = WINDOW,
                          thresholds: dict = DEFAULTS) -> tuple[bool, str, dict]:
    """Screen dispatcher: use the conservative numpy screen for the vectorizable
    breakout family, fall back to the event-driven screen for everything else.

    Sound because the gauntlet — not the screen — is the real gate (it re-tests every
    survivor with honest event-driven replay, OOS, at the rising bar). vscreen's proven
    conservatism (vec_pf <= replay_pf, test 24) means a vectorized PASS never *flatters*
    the honest edge, so the worst case is a handful of extra gauntlet runs, never a
    false edge admitted to the reserve. Reject-side recall loss is the accepted trade."""
    vec = _vectorizable(candidate)
    if vec is None:
        return screen_candidate(candidate, candles, cfg, window=window, thresholds=thresholds)
    from maker.vscreen import vectorized_screen_metrics
    m = vectorized_screen_metrics(candles, vec["lookback"], vec["r_mult"])
    passed, reason = screen_decision(m, thresholds)
    return passed, ("vec:" + reason), m
