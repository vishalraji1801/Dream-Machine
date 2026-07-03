import json
import os
from datetime import datetime

import pytest

from src.position_manager import Position
from src.state_store import StateStore


@pytest.fixture
def store(tmp_path):
    return StateStore(path=str(tmp_path / "bot_state.json"))


def _positions():
    return [
        Position("RELIANCE", "BUY", 2800.0, 10, 2772.0, 2856.0,
                 entry_time=datetime(2026, 7, 3, 10, 15), gtt_id=777),
        Position("TCS", "SELL", 3500.0, 5, 3535.0, 3430.0,
                 entry_time=datetime(2026, 7, 3, 11, 0), trailing_sl_active=True),
    ]


def test_save_and_load_roundtrip(store):
    store.save(daily_pnl=-1250.5, trades_today=4, positions=_positions())
    state = store.load()
    assert state is not None
    assert state["daily_pnl"] == -1250.5
    assert state["trades_today"] == 4
    assert len(state["positions"]) == 2

    p = state["positions"][0]
    assert isinstance(p, Position)
    assert p.symbol == "RELIANCE"
    assert p.gtt_id == 777
    assert p.entry_time == datetime(2026, 7, 3, 10, 15)

    p2 = state["positions"][1]
    assert p2.direction == "SELL"
    assert p2.trailing_sl_active is True


def test_load_returns_none_when_no_file(store):
    assert store.load() is None


def test_load_returns_none_for_stale_date(store, tmp_path):
    store.save(daily_pnl=100.0, trades_today=1, positions=[])
    path = tmp_path / "bot_state.json"
    state = json.loads(path.read_text())
    state["date"] = "2020-01-01"
    path.write_text(json.dumps(state))
    assert store.load() is None


def test_load_returns_none_for_corrupt_json(store, tmp_path):
    (tmp_path / "bot_state.json").write_text("{not valid json!!")
    assert store.load() is None


def test_load_returns_none_for_corrupt_positions(store, tmp_path):
    store.save(daily_pnl=0.0, trades_today=0, positions=_positions())
    path = tmp_path / "bot_state.json"
    state = json.loads(path.read_text())
    del state["positions"][0]["entry_price"]
    path.write_text(json.dumps(state))
    assert store.load() is None


def test_save_with_no_positions(store):
    store.save(daily_pnl=500.0, trades_today=2, positions=[])
    state = store.load()
    assert state["positions"] == []
    assert state["daily_pnl"] == 500.0


def test_clear_removes_file(store, tmp_path):
    store.save(daily_pnl=0.0, trades_today=0, positions=[])
    assert (tmp_path / "bot_state.json").exists()
    store.clear()
    assert not (tmp_path / "bot_state.json").exists()


def test_clear_is_noop_when_no_file(store):
    store.clear()  # should not raise


def test_save_overwrites_previous_state(store):
    store.save(daily_pnl=100.0, trades_today=1, positions=[])
    store.save(daily_pnl=200.0, trades_today=2, positions=[])
    state = store.load()
    assert state["daily_pnl"] == 200.0
    assert state["trades_today"] == 2
