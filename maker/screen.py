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


def screen_candidate(candidate, candles: dict, cfg: dict, window: int = 160,
                     thresholds: dict = DEFAULTS) -> tuple[bool, str, dict]:
    """Compile, run one in-sample backtest, apply the kill logic. Registers the
    compiled fn under the cid only for the duration of the run."""
    from src.backtester import Backtester
    from src.strategy import STRATEGY_REGISTRY
    fn = compile(candidate)
    STRATEGY_REGISTRY[candidate.cid] = fn
    try:
        c = copy.deepcopy(cfg)
        c.setdefault("strategy", {})["name"] = candidate.cid
        # long_only applies to SWING (CNC can't hold shorts overnight); intraday (MIS)
        # may short and square off, so it keeps both sides.
        product = str(c.get("costs", {}).get("product", "delivery")).lower()
        c["strategy"]["long_only"] = product in ("delivery", "cnc")
        res = Backtester(c, window=window).run(candles)
    finally:
        STRATEGY_REGISTRY.pop(candidate.cid, None)
    m = _metrics(res)
    passed, reason = screen_decision(m, thresholds)
    return passed, reason, m
