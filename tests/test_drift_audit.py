"""Commit 8 — Level-3 guards + drift audit (test 10)."""
from src.drift_audit import (Proposal, audit_drift, is_auto_deployable,
                             paper_eligible)


# ── Level-3 deploy guards ─────────────────────────────────────────────────────

def test_level3_never_auto_deploys():
    fully = Proposal("A", "RANGE", {"atr_period": 14}, oos_report={"passed": True},
                     approved=True, validated=True)
    assert is_auto_deployable(fully) is False        # even fully-approved: human merge only


def test_paper_eligible_requires_bounds():
    ok, _ = paper_eligible(Proposal("A", "RANGE", {"atr_period": 14}))
    assert ok is True
    bad, reason = paper_eligible(Proposal("A", "RANGE", {"atr_period": 999}))
    assert bad is False and "bounds" in reason


def test_paper_eligible_step_limit():
    p = Proposal("A", "RANGE", {"atr_period": 20})
    ok, _ = paper_eligible(p, prev_params={"atr_period": 19}, max_step_pct=10)
    assert ok is True                                 # ~5% move
    big, reason = paper_eligible(p, prev_params={"atr_period": 10}, max_step_pct=10)
    assert big is False and "moves" in reason         # 100% move


# ── test 10: drift audit flags an underperforming adaptation ──────────────────

def test_audit_flags_underperformance():
    adaptation = [10, -30, 5, -20] * 10               # 40 trades, net negative-ish
    baseline = [10, -5, 5, -2] * 10                   # baseline clearly better
    v = audit_drift(adaptation, baseline, min_samples=20)
    assert v.beating_baseline is False
    assert v.recommend_revert is True
    assert v.delta < 0
    assert v.reason == "underperforming_baseline_revert"


def test_audit_confirms_outperformance():
    adaptation = [20, -5] * 15                         # 30 trades, strong
    baseline = [5, -5] * 15
    v = audit_drift(adaptation, baseline, min_samples=20)
    assert v.beating_baseline is True
    assert v.recommend_revert is False
    assert v.delta > 0


def test_audit_insufficient_samples_no_revert():
    v = audit_drift([100, 100], [1, 1], min_samples=20)   # only 2 trades
    assert v.recommend_revert is False                 # don't revert on thin evidence
    assert v.beating_baseline is False
    assert v.reason == "insufficient_samples"


def test_audit_margin_required():
    # adaptation barely ahead but below the required margin -> revert
    v = audit_drift([1] * 30, [0] * 30, min_samples=20, margin=100)
    assert v.beating_baseline is False and v.recommend_revert is True


def test_purity():
    import src.drift_audit as m
    src = open(m.__file__, encoding="utf-8").read()
    assert "datetime.now(" not in src and "kiteconnect" not in src
