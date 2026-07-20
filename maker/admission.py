"""maker/admission.py — paper & portfolio admission (Strategy Maker, spec section 8).

An ALIVE candidate (passed the reserve) enters PAPER under the existing swing gate.
Only after clearing paper does it seek a live-router slot, and admission there also
requires a correlation check: if its daily returns correlate >= 0.7 with an existing
live strategy it REPLACES that correlated sibling rather than joining — the portfolio
must not accumulate five copies of the same exposure.
"""
import numpy as np

SWING_GATE = {"min_weeks": 8, "min_round_trips": 30, "min_pf": 1.2, "max_divergence": 0.30}
MAX_CORR = 0.7


def paper_book_for(candidate) -> str:
    """Which sleeve's paper book an ALIVE candidate joins — never the other one."""
    return candidate.sleeve


def is_tradeable(candidate, cfg: dict) -> bool:
    """An ALIVE intraday candidate stays inert while intraday.enabled is false — it
    accumulates as the evidence required to justify re-enabling the sleeve (section
    11.3), but does not trade. Swing always tradeable when the swing sleeve is on."""
    if candidate.sleeve == "intraday":
        return bool(cfg.get("intraday", {}).get("enabled", False))
    return bool(cfg.get("swing", {}).get("enabled", True))


def swing_paper_gate(paper: dict, backtest_pf: float, gate: dict = SWING_GATE):
    """paper: {weeks, round_trips, pf}. Returns (passed, reason)."""
    if paper["weeks"] < gate["min_weeks"]:
        return False, "insufficient_paper_history"
    if paper["round_trips"] < gate["min_round_trips"]:
        return False, "insufficient_round_trips"
    if paper["pf"] < gate["min_pf"]:
        return False, "paper_pf_below_bar"
    divergence = abs(paper["pf"] - backtest_pf) / backtest_pf if backtest_pf else 1.0
    if divergence > gate["max_divergence"]:
        return False, "paper_backtest_divergence"
    return True, "pass"


def _corr(a, b) -> float:
    a, b = np.asarray(a, float), np.asarray(b, float)
    n = min(len(a), len(b))
    if n < 3:
        return 0.0
    a, b = a[-n:], b[-n:]
    if a.std() == 0 or b.std() == 0:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def correlation_admission(cand_returns, live_returns_by_strategy: dict, max_corr: float = MAX_CORR):
    """Returns (action, detail). action: 'join' (uncorrelated enough) | 'replace'
    (too correlated with a live sibling — take its slot) ."""
    if not live_returns_by_strategy:
        return "join", {"max_corr": 0.0, "with": None, "all": {}}
    corrs = {name: _corr(cand_returns, r) for name, r in live_returns_by_strategy.items()}
    worst_name = max(corrs, key=lambda k: abs(corrs[k]))
    worst = corrs[worst_name]
    action = "replace" if abs(worst) >= max_corr else "join"
    return action, {"max_corr": round(worst, 3), "with": worst_name, "all": corrs}
