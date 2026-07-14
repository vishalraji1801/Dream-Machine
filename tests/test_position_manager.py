from datetime import datetime
from unittest.mock import patch

import pytest

from src.position_manager import Position, PositionManager


@pytest.fixture
def cfg():
    return {
        "risk": {
            "trailing_sl_enabled": True,
            "trailing_sl_activation_pct": 1.0,
            "trailing_sl_step_pct": 0.5,
        },
        "trading": {
            "square_off_time": "15:15",
        },
    }


@pytest.fixture
def pm(cfg):
    return PositionManager(cfg)


# ── Basic position management ─────────────────────────────────────────────────

def test_add_position(pm):
    pm.add_position("RELIANCE", "BUY", 2845.0, 5, 2816.55, 2901.9)
    assert pm.open_count() == 1
    assert pm.get_open_positions()[0].symbol == "RELIANCE"


def test_remove_position(pm):
    pm.add_position("TCS", "BUY", 3500.0, 2, 3465.0, 3570.0)
    removed = pm.remove_position("TCS")
    assert removed.symbol == "TCS"
    assert pm.open_count() == 0


def test_remove_nonexistent_returns_none(pm):
    assert pm.remove_position("NOTEXIST") is None


def test_open_count(pm):
    pm.add_position("A", "BUY", 100.0, 1, 99.0, 102.0)
    pm.add_position("B", "BUY", 200.0, 1, 198.0, 204.0)
    assert pm.open_count() == 2


# ── Exit checks ───────────────────────────────────────────────────────────────

def test_buy_sl_hit(pm):
    pm.add_position("INFY", "BUY", 1500.0, 10, 1485.0, 1530.0)
    flag, reason = pm.check_exit("INFY", 1480.0)
    assert flag is True and reason == "sl_hit"


def test_buy_target_hit(pm):
    pm.add_position("INFY", "BUY", 1500.0, 10, 1485.0, 1530.0)
    flag, reason = pm.check_exit("INFY", 1535.0)
    assert flag is True and reason == "target_hit"


def test_buy_no_exit(pm):
    pm.add_position("INFY", "BUY", 1500.0, 10, 1485.0, 1530.0)
    flag, _ = pm.check_exit("INFY", 1510.0)
    assert flag is False


def test_sell_sl_hit(pm):
    pm.add_position("TCS", "SELL", 3500.0, 2, 3535.0, 3430.0)
    flag, reason = pm.check_exit("TCS", 3540.0)
    assert flag is True and reason == "sl_hit"


def test_sell_target_hit(pm):
    pm.add_position("TCS", "SELL", 3500.0, 2, 3535.0, 3430.0)
    flag, reason = pm.check_exit("TCS", 3425.0)
    assert flag is True and reason == "target_hit"


def test_exit_unknown_symbol(pm):
    flag, reason = pm.check_exit("UNKNOWN", 1000.0)
    assert flag is False and reason == ""


# ── Trailing SL ───────────────────────────────────────────────────────────────

def test_trailing_sl_activates_at_threshold(pm):
    pm.add_position("HDFC", "BUY", 1000.0, 5, 990.0, 1020.0)
    new_sl = pm.update_trailing_sl("HDFC", 1015.0)
    assert new_sl is not None
    assert new_sl >= 1000.0


def test_trailing_sl_not_activated_below_threshold(pm):
    pm.add_position("HDFC", "BUY", 1000.0, 5, 990.0, 1020.0)
    new_sl = pm.update_trailing_sl("HDFC", 1005.0)
    assert new_sl is None


def test_trailing_sl_advances_with_price(pm):
    pm.add_position("HDFC", "BUY", 1000.0, 5, 990.0, 1025.0)
    pm.update_trailing_sl("HDFC", 1015.0)
    sl_after_first = pm.get_open_positions()[0].stop_loss
    pm.update_trailing_sl("HDFC", 1020.0)
    sl_after_second = pm.get_open_positions()[0].stop_loss
    assert sl_after_second >= sl_after_first


def test_trailing_sl_sell_direction(pm):
    pm.add_position("SBIN", "SELL", 1000.0, 10, 1010.0, 980.0)
    new_sl = pm.update_trailing_sl("SBIN", 985.0)
    assert new_sl is not None
    assert new_sl <= 1000.0


# ── EOD square-off ────────────────────────────────────────────────────────────

def test_square_off_before_time_returns_empty(pm):
    pm.add_position("X", "BUY", 100.0, 1, 99.0, 102.0)
    with patch("src.position_manager.datetime") as mock_dt:
        mock_dt.now.return_value.time.return_value = datetime(2026, 7, 2, 14, 0, 0).time()
        positions = pm.get_positions_for_square_off()
    assert positions == []


def test_square_off_at_time_returns_all(pm):
    pm.add_position("X", "BUY", 100.0, 1, 99.0, 102.0)
    pm.add_position("Y", "SELL", 200.0, 2, 202.0, 196.0)
    with patch("src.position_manager.datetime") as mock_dt:
        mock_dt.now.return_value.time.return_value = datetime(2026, 7, 2, 15, 15, 0).time()
        positions = pm.get_positions_for_square_off()
    assert len(positions) == 2


# ── Unrealized P&L ────────────────────────────────────────────────────────────

def test_unrealized_pnl_buy_profit():
    pos = Position("X", "BUY", 1000.0, 10, 990.0, 1020.0)
    assert pos.unrealized_pnl(1010.0) == pytest.approx(100.0)


def test_unrealized_pnl_sell_profit():
    pos = Position("X", "SELL", 1000.0, 10, 1010.0, 980.0)
    assert pos.unrealized_pnl(990.0) == pytest.approx(100.0)


# ── GTT ID ───────────────────────────────────────────────────────────────────

def test_position_gtt_id_default_none(pm):
    pm.add_position("X", "BUY", 100.0, 1, 99.0, 102.0)
    pos = pm.get_open_positions()[0]
    assert pos.gtt_id is None


def test_set_gtt_id_stores_value(pm):
    pm.add_position("X", "BUY", 100.0, 1, 99.0, 102.0)
    pm.set_gtt_id("X", 12345)
    pos = pm.get_open_positions()[0]
    assert pos.gtt_id == 12345


def test_set_gtt_id_noop_for_unknown_symbol(pm):
    pm.set_gtt_id("UNKNOWN", 99)  # should not raise


# ── Crash recovery restore ────────────────────────────────────────────────────

def test_restore_readopts_positions(pm):
    saved = [
        Position("RELIANCE", "BUY", 2800.0, 10, 2772.0, 2856.0, gtt_id=777),
        Position("TCS", "SELL", 3500.0, 5, 3535.0, 3430.0),
    ]
    pm.restore(saved)
    assert pm.open_count() == 2
    pos = next(p for p in pm.get_open_positions() if p.symbol == "RELIANCE")
    assert pos.gtt_id == 777
    # restored positions behave normally
    flag, reason = pm.check_exit("RELIANCE", 2770.0)
    assert flag is True and reason == "sl_hit"
