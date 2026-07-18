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


def staged_screen(candidate, candles: dict, cfg: dict, subset: list, window: int = 160,
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


def screen_candidate(candidate, candles: dict, cfg: dict, window: int = 160,
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
    passed, reason = screen_decision(m, thresholds)
    return passed, reason, m
