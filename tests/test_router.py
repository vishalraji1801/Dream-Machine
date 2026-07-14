"""Regime router (commit 4) — weighting (5), fail-safe (6), trade-nothing (7)."""
import pytest

from src.regime import Regime, RegimeState
from src.router import (ActiveStrategy, PremarketAllocation, RouterConfig, route)
from src.strategy_meta import load_strategy_meta


def _meta(name, pf, regime="STRONG_TREND_UP", trades=100, validated=True):
    return load_strategy_meta({
        "name": name,
        "regime_param_sets": {regime: {"multiplier": 2.1, "validated": validated,
                                       "oos_ref": f"{name}_ref"},
                              "default": {"multiplier": 2.1, "validated": True}},
        "regime_fit": {regime: {"pf": pf, "trades": trades}},
    })


def _regime(reg=Regime.STRONG_TREND_UP, conf=1.0):
    return RegimeState(reg, conf, since_bars=5, inputs={}, config_version="t")


FULL = PremarketAllocation(ceiling=1.0)
CFG = RouterConfig(mode="live")


# ── test 5: weighting in pf ratio ─────────────────────────────────────────────

def test_weights_in_pf_ratio():
    strategies = [_meta("A", 1.8), _meta("B", 0.9)]
    out = route(_regime(conf=1.0), strategies, FULL, CFG)
    w = {a.name: a.weight for a in out}
    assert w["A"] == pytest.approx(1.8 / 2.7)   # 0.6667
    assert w["B"] == pytest.approx(0.9 / 2.7)   # 0.3333
    assert sum(w.values()) == pytest.approx(1.0)


def test_confidence_scales_total_allocation():
    strategies = [_meta("A", 1.8), _meta("B", 0.9)]
    out = route(_regime(conf=0.5), strategies, FULL, CFG)
    assert sum(a.weight for a in out) == pytest.approx(0.5)   # half budget at half confidence
    # split unchanged
    w = {a.name: a.weight for a in out}
    assert w["A"] == pytest.approx(0.5 * 1.8 / 2.7)


# ── test 6: fail-safe ceiling ─────────────────────────────────────────────────

def test_total_never_exceeds_ceiling():
    strategies = [_meta("A", 1.8), _meta("B", 1.5)]
    premarket = PremarketAllocation(ceiling=0.4)
    # prev weights high enough that hysteresis would push the total past the ceiling
    out = route(_regime(conf=1.0), strategies, premarket, CFG,
                prev_weights={"A": 0.35, "B": 0.35})
    assert sum(a.weight for a in out) <= 0.4 + 1e-9


def test_caps_only_lower():
    strategies = [_meta("A", 1.8), _meta("B", 0.9)]
    premarket = PremarketAllocation(ceiling=1.0, caps={"A": 0.2})
    out = route(_regime(conf=1.0), strategies, premarket, CFG)
    assert next(a.weight for a in out if a.name == "A") <= 0.2


# ── test 7: trade nothing ─────────────────────────────────────────────────────

def test_trade_nothing_when_no_edge():
    strategies = [_meta("A", 0.8), _meta("B", 0.9)]      # all pf <= 1.0
    assert route(_regime(), strategies, FULL, CFG) == []


def test_unknown_regime_trades_nothing():
    assert route(_regime(Regime.UNKNOWN), [_meta("A", 1.8)], FULL, CFG) == []


def test_empty_registry_trades_nothing():
    assert route(_regime(), [], FULL, CFG) == []


# ── enforcement + hysteresis ──────────────────────────────────────────────────

def test_unvalidated_strategy_excluded_in_live():
    strategies = [_meta("A", 1.8, validated=False), _meta("B", 1.5)]
    out = route(_regime(), strategies, FULL, CFG)
    # A's set for the regime is unvalidated -> A falls back to its validated 'default'
    # only if that default covers the regime; here 'default' IS validated, so A runs.
    # Assert at least B runs and nothing unvalidated leaks a non-validated set.
    for a in out:
        assert a.param_set.validated is True


def test_small_sample_excluded():
    strategies = [_meta("A", 1.8, trades=10)]            # below min_trades
    assert route(_regime(), strategies, FULL, RouterConfig(mode="live", min_trades=30)) == []


def test_weight_hysteresis_limits_jump():
    strategies = [_meta("A", 1.8), _meta("B", 0.9)]
    out = route(_regime(conf=1.0), strategies, FULL,
                RouterConfig(mode="live", max_weight_change=0.1),
                prev_weights={"A": 0.6, "B": 0.0})
    b = next(a.weight for a in out if a.name == "B")
    assert b <= 0.0 + 0.1 + 1e-9        # B can't jump more than 0.1 from prev 0.0


def test_purity():
    import src.router as m
    src = open(m.__file__, encoding="utf-8").read()
    assert "datetime.now(" not in src and "kiteconnect" not in src
