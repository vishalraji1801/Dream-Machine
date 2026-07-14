import pytest

from src.risk_manager import RiskManager


@pytest.fixture
def cfg():
    return {
        "risk": {
            "total_capital": 500000,
            "max_risk_per_trade_pct": 1.0,
            "max_open_positions": 3,
            "max_position_size_pct": 20.0,
            "order_value_cap": 120000,
            "trailing_sl_enabled": True,
            "trailing_sl_activation_pct": 1.0,
            "trailing_sl_step_pct": 0.5,
            "max_daily_loss": 10000,
            "max_trades_per_day": 8,
            "max_consecutive_api_errors": 3,
            "min_margin_threshold": 25000,
        },
        "trading": {
            "market_open": "09:15",
            "square_off_time": "15:15",
        },
    }


@pytest.fixture
def rm(cfg):
    return RiskManager(cfg)


# ── Pre-trade ─────────────────────────────────────────────────────────────────

def test_pre_trade_passes(rm):
    ok, reason = rm.check_pre_trade(50000, 100000, 1)
    assert ok is True and reason == ""


def test_pre_trade_blocks_over_cap(rm):
    ok, reason = rm.check_pre_trade(130000, 200000, 0)
    assert ok is False
    assert "cap" in reason or "order_value" in reason


def test_pre_trade_blocks_max_position_size(rm):
    ok, reason = rm.check_pre_trade(110000, 200000, 0)
    assert ok is False


def test_pre_trade_blocks_max_positions(rm):
    ok, reason = rm.check_pre_trade(50000, 200000, 3)
    assert ok is False
    assert "positions" in reason


def test_pre_trade_blocks_low_margin(rm):
    ok, reason = rm.check_pre_trade(50000, 20000, 0)
    assert ok is False
    assert "margin" in reason


# ── Circuit breakers ──────────────────────────────────────────────────────────

def test_no_breaker_by_default(rm):
    ok, _ = rm.check_circuit_breakers()
    assert ok is True


def test_daily_loss_halts(rm):
    rm.record_pnl(-10001)
    ok, reason = rm.check_circuit_breakers()
    assert ok is False and rm.is_halted()
    assert "loss" in reason.lower()


def test_max_trades_halts(rm):
    for _ in range(8):
        rm.record_trade()
    ok, _ = rm.check_circuit_breakers()
    assert ok is False and rm.is_halted()


def test_api_errors_halt(rm):
    for _ in range(3):
        rm.record_api_error()
    ok, _ = rm.check_circuit_breakers()
    assert ok is False and rm.is_halted()


def test_already_halted_returns_false(rm):
    rm.record_pnl(-20000)
    rm.check_circuit_breakers()
    ok, reason = rm.check_circuit_breakers()
    assert ok is False and reason == "already_halted"


def test_pre_trade_blocked_when_halted(rm):
    rm.record_pnl(-20000)
    rm.check_circuit_breakers()
    ok, reason = rm.check_pre_trade(50000, 200000, 0)
    assert ok is False and reason == "bot_halted"


def test_reset_clears_halted_state(rm):
    rm.record_pnl(-20000)
    rm.check_circuit_breakers()
    rm.reset_daily_counters()
    ok, _ = rm.check_circuit_breakers()
    assert ok is True and not rm.is_halted()


# ── Position sizing ───────────────────────────────────────────────────────────

def test_calculate_quantity_within_risk(rm):
    qty = rm.calculate_quantity(1000.0, 990.0)
    assert qty > 0
    assert qty * (1000.0 - 990.0) <= 5000


def test_calculate_quantity_capped_by_position_size(rm):
    qty = rm.calculate_quantity(1000.0, 999.0)
    assert qty * 1000.0 <= 100000 + 1000


def test_calculate_quantity_zero_risk(rm):
    assert rm.calculate_quantity(1000.0, 1000.0) == 0


# ── Crash recovery restore ────────────────────────────────────────────────────

def test_restore_counters(rm):
    rm.restore_counters(daily_pnl=-4500.0, trades_today=6)
    assert rm._daily_pnl == -4500.0
    assert rm._trades_today == 6


def test_restored_counters_feed_circuit_breakers(rm):
    rm.restore_counters(daily_pnl=-10000.0, trades_today=2)
    ok, reason = rm.check_circuit_breakers()
    assert ok is False
    assert "loss" in reason.lower()


# ── V2 P6: kill switch & sector cap ───────────────────────────────────────────

def test_kill_switch_halts_on_giveback(cfg):
    cfg["risk"]["max_giveback_from_peak"] = 500
    rm = RiskManager(cfg)
    rm.record_pnl(1000.0)   # peak = 1000
    rm.record_pnl(-600.0)   # daily = 400, gave back 600 >= 500
    ok, reason = rm.check_circuit_breakers()
    assert ok is False
    assert "kill switch" in reason.lower()


def test_kill_switch_not_triggered_within_limit(cfg):
    cfg["risk"]["max_giveback_from_peak"] = 500
    rm = RiskManager(cfg)
    rm.record_pnl(1000.0)
    rm.record_pnl(-300.0)   # gave back only 300 < 500
    ok, _ = rm.check_circuit_breakers()
    assert ok is True


def test_kill_switch_disabled_when_zero(cfg):
    cfg["risk"]["max_giveback_from_peak"] = 0
    rm = RiskManager(cfg)
    rm.record_pnl(1000.0)
    rm.record_pnl(-900.0)
    ok, _ = rm.check_circuit_breakers()
    assert ok is True


def test_sector_cap_blocks_third_bank(cfg):
    cfg["risk"]["max_positions_per_sector"] = 2
    cfg["sectors"] = {"HDFCBANK": "BANK", "ICICIBANK": "BANK", "SBIN": "BANK"}
    rm = RiskManager(cfg)
    ok, reason = rm.check_sector_cap("SBIN", ["HDFCBANK", "ICICIBANK"])
    assert ok is False
    assert "BANK" in reason


def test_sector_cap_allows_within_limit(cfg):
    cfg["risk"]["max_positions_per_sector"] = 2
    cfg["sectors"] = {"HDFCBANK": "BANK", "ICICIBANK": "BANK", "TCS": "IT"}
    rm = RiskManager(cfg)
    assert rm.check_sector_cap("ICICIBANK", ["HDFCBANK"])[0] is True
    assert rm.check_sector_cap("TCS", ["HDFCBANK", "ICICIBANK"])[0] is True


def test_sector_cap_disabled_without_config(cfg):
    rm = RiskManager(cfg)  # no max_positions_per_sector, no sectors
    assert rm.check_sector_cap("SBIN", ["HDFCBANK", "ICICIBANK"])[0] is True
