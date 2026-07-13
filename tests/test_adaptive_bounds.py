"""Commit 7 — hard-bounds enforcement + fallback/alert (test 9)."""
from src.adaptive_bounds import validate_params
from src.regime import Regime, RegimeState
from src.router import PremarketAllocation, RouterConfig, route
from src.strategy_meta import bounded_param_set, load_strategy_meta

FULL, CFG = PremarketAllocation(1.0), RouterConfig(mode="live")


def _regime():
    return RegimeState(Regime.STRONG_TREND_UP, 1.0, 5, {}, "v")


def _meta(regime_params, default_params, pf=1.8):
    return load_strategy_meta({
        "name": "X",
        "regime_param_sets": {
            "STRONG_TREND_UP": {**regime_params, "validated": True},
            "default": {**default_params, "validated": True},
        },
        "regime_fit": {"STRONG_TREND_UP": {"pf": pf, "trades": 100}},
    })


# ── validator ─────────────────────────────────────────────────────────────────

def test_validate_params_bounds():
    assert validate_params({"atr_period": 14}) is None            # in [5,30]
    assert "outside" in validate_params({"atr_period": 999})       # over max
    assert "outside" in validate_params({"supertrend_mult": 0.1})  # under min
    assert validate_params({"unbounded_key": 12345}) is None       # not a tunable here


# ── test 9: out-of-bounds set rejected, falls back to default + alert ──────────

def test_out_of_bounds_falls_back_to_default_with_alert():
    meta = _meta({"atr_period": 999}, {"atr_period": 14})
    alerts = []
    ps = bounded_param_set(meta, Regime.STRONG_TREND_UP, "live", on_alert=alerts.append)
    assert ps is not None and ps.params["atr_period"] == 14          # fell back
    assert any("outside" in a for a in alerts)


def test_router_uses_default_on_out_of_bounds():
    meta = _meta({"atr_period": 999}, {"atr_period": 14})
    alerts = []
    out = route(_regime(), [meta], FULL, CFG, on_alert=alerts.append)
    assert len(out) == 1 and out[0].param_set.params["atr_period"] == 14
    assert alerts


def test_disabled_when_default_also_out_of_bounds():
    meta = _meta({"atr_period": 999}, {"atr_period": 888})
    alerts = []
    out = route(_regime(), [meta], FULL, CFG, on_alert=alerts.append)
    assert out == []                                                # strategy dropped
    assert any("disabled" in a for a in alerts)


def test_in_bounds_set_used_directly():
    meta = _meta({"atr_period": 12}, {"atr_period": 14})
    out = route(_regime(), [meta], FULL, CFG)
    assert len(out) == 1 and out[0].param_set.params["atr_period"] == 12
