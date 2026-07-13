"""Commit 5 — routing decisions persisted to the ledger with mode/run tagging."""
import os

import pytest

from src.regime import Regime, RegimeState
from src.router import (PremarketAllocation, RouterConfig, route, routing_records)
from src.strategy_meta import load_strategy_meta
from src.trade_db import TradeDB


@pytest.fixture
def db(tmp_path):
    return TradeDB(path=str(tmp_path / "trades.db"))


def _meta(name, pf):
    return load_strategy_meta({
        "name": name,
        "regime_param_sets": {"STRONG_TREND_UP": {"multiplier": 2.1, "validated": True, "oos_ref": f"{name}_r"}},
        "regime_fit": {"STRONG_TREND_UP": {"pf": pf, "trades": 100}},
    })


def test_record_and_read_routing(db):
    regime = RegimeState(Regime.STRONG_TREND_UP, 0.8, 5, {}, "cfgv1")
    active = route(regime, [_meta("A", 1.8), _meta("B", 1.2)],
                   PremarketAllocation(1.0), RouterConfig(mode="paper"))
    db.record_routing(source="paper", regime=regime.regime.value,
                      confidence=regime.confidence, active=routing_records(active),
                      run_id="run42", config_version="cfgv1")
    rows = db.routing()
    assert len(rows) == 1
    r = rows[0]
    assert r["source"] == "paper" and r["run_id"] == "run42" and r["config_version"] == "cfgv1"
    assert r["regime"] == "STRONG_TREND_UP" and r["confidence"] == 0.8
    names = {a["name"] for a in r["active"]}
    assert names == {"A", "B"}
    assert all("weight" in a and "oos_ref" in a for a in r["active"])


def test_routing_source_filter(db):
    regime = RegimeState(Regime.RANGE, 0.5, 3, {}, "v")
    db.record_routing(source="paper", regime="RANGE", confidence=0.5, active=[])
    db.record_routing(source="backtest", regime="RANGE", confidence=0.5, active=[])
    assert len(db.routing(source="paper")) == 1
    assert len(db.routing()) == 2


def test_trade_nothing_persists_empty(db):
    db.record_routing(source="live", regime="HIGH_VOL_CHOP", confidence=0.3, active=[])
    rows = db.routing()
    assert rows[0]["active"] == []
