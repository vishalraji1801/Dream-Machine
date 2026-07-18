"""maker/constraints.py — generation-time rejects (Strategy Maker, spec section 3).

Free kills before any backtest. A candidate is GEN_REJECTed (and logged as a trial
with status GEN_REJECT) when it:
  - fails the parsimony budget (enforced upstream in grammar.make_candidate; re-checked
    here for candidates built by other means),
  - fails the TURNOVER budget: estimated gross edge per trade < cost_multiple_min x the
    round-trip cost for the target product (delivery ~0.24% -> required gross ~0.72%),
  - is a short on CNC (untradeable overnight — the bug class already hit),
  - duplicates an existing cid.

The turnover math rarely bites daily swing (daily moves clear costs) but is the filter
that kills fast intraday candidates once the intraday sleeve lands (section 11.3).
"""
from maker.grammar import Candidate

# Nominal daily ATR as a % of price, per product, used ONLY for the pre-backtest edge
# estimate. Deliberately conservative; the real edge is measured later by the screen.
_NOMINAL_ATR_PCT = {"delivery": 2.0, "cnc": 2.0, "intraday": 0.5, "mis": 0.5}


def round_trip_cost_pct(product: str) -> float:
    """Round-trip charges as a % of one leg's value, from the real cost model."""
    from src.costs import estimate_costs
    leg = 100000.0
    cost = estimate_costs(leg, leg, {"costs": {"product": product}})
    return cost / leg * 100.0


def estimate_edge_pct(candidate: Candidate, product: str) -> float:
    """Rough gross move the exit implies, as a % of price. Pre-backtest proxy only."""
    atrp = _NOMINAL_ATR_PCT.get(product.lower(), 2.0)
    ex = candidate.blocks.get("exit")
    if ex is None:
        return atrp
    if ex.name == "atr_trail":
        return ex.params.get("mult", 5) * atrp * 0.6          # partial capture riding a trend
    if ex.name == "r_multiple":
        return ex.params.get("r", 2) * 1.5 * atrp             # target = r x (1.5xATR) risk
    if ex.name == "opposite_band":
        return 2.5 * atrp                                     # touch -> mean
    if ex.name == "ma_cross_exit":
        return 1.5 * atrp
    return atrp


def check(candidate: Candidate, product: str = None, seen_cids=(),
          cost_multiple_min: float = 3.0) -> tuple[bool, str, dict]:
    """Return (ok, reason, detail). reason is 'ok' when it passes; otherwise a
    GEN_REJECT code with the supporting math in detail (recorded on the trial row).
    product defaults to the candidate's own (swing->delivery, intraday->intraday)."""
    product = product or getattr(candidate, "product", "delivery")
    if candidate.n_conditions > 3 or candidate.n_params > 4:
        return False, "parsimony", {"n_conditions": candidate.n_conditions,
                                    "n_params": candidate.n_params}
    if candidate.direction in ("short", "both") and product.lower() in ("delivery", "cnc"):
        return False, "short_on_cnc", {"direction": candidate.direction, "product": product}
    if candidate.cid in set(seen_cids):
        return False, "duplicate", {"cid": candidate.cid}
    rt = round_trip_cost_pct(product)
    required = cost_multiple_min * rt
    edge = estimate_edge_pct(candidate, product)
    detail = {"round_trip_cost_pct": round(rt, 3),
              "required_gross_pct": round(required, 3),
              "est_edge_pct": round(edge, 3),
              "cost_multiple_min": cost_multiple_min}
    if edge < required:
        return False, "turnover_budget", detail
    return True, "ok", detail
