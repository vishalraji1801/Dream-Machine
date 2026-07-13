"""Strategy metadata (commit 2) — loader + validated-flag enforcement (test 4)."""
import textwrap

import pytest

from src.regime import Regime
from src.strategy_meta import (fit_for, load_strategy_dir, load_strategy_meta,
                               param_set_for)

DATA = {
    "name": "supertrend",
    "regime_param_sets": {
        "STRONG_TREND_UP": {"atr_period": 10, "multiplier": 2.1, "validated": True, "oos_ref": "wf17"},
        "RANGE": {"enabled": False},
        "HIGH_VOL_CHOP": {"atr_period": 14, "multiplier": 3.3, "validated": False, "oos_ref": "exp"},
        "default": {"atr_period": 10, "multiplier": 2.1, "validated": True, "oos_ref": "base"},
    },
    "regime_fit": {
        "STRONG_TREND_UP": {"pf": 1.8, "trades": 140, "source": "ledger"},
        "HIGH_VOL_CHOP": {"pf": 0.9, "trades": 12, "source": "ledger"},
    },
}


@pytest.fixture
def meta():
    return load_strategy_meta(DATA)


# ── test 4: unvalidated set blocked in live/paper, allowed in research ─────────

def test_validated_set_selectable_in_live(meta):
    ps = param_set_for(meta, Regime.STRONG_TREND_UP, "live")
    assert ps is not None and ps.params["multiplier"] == 2.1 and ps.oos_ref == "wf17"


def test_unvalidated_blocked_in_live_and_paper(meta):
    assert param_set_for(meta, Regime.HIGH_VOL_CHOP, "live") is None
    assert param_set_for(meta, Regime.HIGH_VOL_CHOP, "paper") is None


def test_unvalidated_allowed_in_research(meta):
    assert param_set_for(meta, Regime.HIGH_VOL_CHOP, "backtest").params["multiplier"] == 3.3
    assert param_set_for(meta, Regime.HIGH_VOL_CHOP, "research").params["multiplier"] == 3.3


def test_disabled_regime_returns_none(meta):
    assert param_set_for(meta, Regime.RANGE, "live") is None


def test_unknown_regime_falls_back_to_default(meta):
    ps = param_set_for(meta, Regime.QUIET, "live")
    assert ps is not None and ps.oos_ref == "base"


# ── regime_fit + small-sample guard ───────────────────────────────────────────

def test_fit_returned_when_enough_trades(meta):
    fit = fit_for(meta, Regime.STRONG_TREND_UP, min_trades=30)
    assert fit is not None and fit.pf == 1.8


def test_fit_none_below_min_trades(meta):
    assert fit_for(meta, Regime.HIGH_VOL_CHOP, min_trades=30) is None   # only 12 trades
    assert fit_for(meta, Regime.QUIET, min_trades=30) is None           # absent


# ── loader ────────────────────────────────────────────────────────────────────

def test_load_strategy_dir(tmp_path):
    (tmp_path / "supertrend.yaml").write_text(textwrap.dedent("""
        name: supertrend
        regime_param_sets:
          STRONG_TREND_UP: {atr_period: 10, multiplier: 2.1, validated: true, oos_ref: wf17}
          default: {atr_period: 10, multiplier: 2.1, validated: true}
        regime_fit:
          STRONG_TREND_UP: {pf: 1.8, trades: 140}
    """), encoding="utf-8")
    metas = load_strategy_dir(str(tmp_path))
    assert "supertrend" in metas
    assert param_set_for(metas["supertrend"], Regime.STRONG_TREND_UP, "live").params["atr_period"] == 10


def test_unknown_regime_key_skipped():
    meta = load_strategy_meta({"name": "x", "regime_param_sets": {"BOGUS": {"a": 1}}})
    assert meta.regime_param_sets == {}
