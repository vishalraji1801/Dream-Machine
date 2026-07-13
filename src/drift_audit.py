"""
Level 3 — continuous re-optimization scaffolding (regime router, commit 8). PURE.
PAPER-ONLY by construction; nothing here can auto-deploy to live.

Two pieces:
  1. Proposal + guards — a re-fitted param set is `validated: false` until it ships
     with a walk-forward OOS report AND a human approval. `is_auto_deployable` is
     hard-wired to False: Level 3 changes are merged by a person, never by code.
     A proposal may run in PAPER only, and only within hard bounds, ±step limit.
  2. Drift audit — compare adaptation P&L against the fixed-baseline counterfactual
     over a window. If adaptation is not measurably beating baseline, recommend
     auto-revert. Most of the time it won't beat baseline — the healthy result.
"""
from dataclasses import dataclass, field
from typing import Optional

from src.adaptive_bounds import validate_params


# ── Level-3 proposal + deploy guards ──────────────────────────────────────────

@dataclass(frozen=True)
class Proposal:
    strategy: str
    regime: str
    params: dict
    oos_report: Optional[dict] = None   # walk-forward report on UNSEEN data
    approved: bool = False              # explicit human approval (never automated)
    validated: bool = False


def is_auto_deployable(_p: Proposal) -> bool:
    """Level-3 proposals are NEVER auto-deployed to live — deployment is a human
    git merge. Always False, on purpose."""
    return False


def paper_eligible(p: Proposal, bounds: Optional[dict] = None,
                   prev_params: Optional[dict] = None,
                   max_step_pct: float = 10.0) -> tuple[bool, str]:
    """May this proposal run in PAPER for evaluation? Only if every value is in
    hard bounds and moves at most ±max_step_pct from the current value."""
    err = validate_params(p.params, bounds)
    if err:
        return False, f"out of bounds: {err}"
    if prev_params:
        for k, v in p.params.items():
            old = prev_params.get(k)
            if isinstance(old, (int, float)) and isinstance(v, (int, float)) and old:
                if abs(v - old) / abs(old) * 100 > max_step_pct + 1e-9:
                    return False, f"{k} moves >{max_step_pct}% ({old}->{v})"
    return True, "paper_ok"


# ── drift audit ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DriftVerdict:
    beating_baseline: bool
    adaptation_net: float
    baseline_net: float
    delta: float
    samples: int
    recommend_revert: bool
    reason: str


def audit_drift(adaptation_pnls: list, baseline_pnls: list,
                min_samples: int = 20, margin: float = 0.0) -> DriftVerdict:
    """
    Compare per-trade P&L of the adaptive system vs its fixed-baseline
    counterfactual over the same trades. Recommends revert when adaptation is not
    beating baseline by at least `margin` over a meaningful window.
    """
    n = min(len(adaptation_pnls), len(baseline_pnls))
    a_net = round(sum(adaptation_pnls[:n]), 2)
    b_net = round(sum(baseline_pnls[:n]), 2)
    delta = round(a_net - b_net, 2)

    if n < min_samples:
        return DriftVerdict(False, a_net, b_net, delta, n, recommend_revert=False,
                            reason="insufficient_samples")
    beating = delta > margin
    return DriftVerdict(beating, a_net, b_net, delta, n,
                        recommend_revert=not beating,
                        reason="beating_baseline" if beating
                        else "underperforming_baseline_revert")
