from datetime import date, datetime

import pytest

from src.market_calendar import MarketCalendar


@pytest.fixture
def cal():
    cfg = {"trading": {
        "market_open": "09:15", "market_close": "15:30",
        "holidays": ["2026-01-26", "2026-12-25"],
    }}
    return MarketCalendar(cfg)


# ── is_trading_day ────────────────────────────────────────────────────────────

def test_weekday_is_trading_day(cal):
    assert cal.is_trading_day(date(2026, 7, 3)) is True  # Friday


def test_saturday_is_not_trading_day(cal):
    assert cal.is_trading_day(date(2026, 7, 4)) is False


def test_sunday_is_not_trading_day(cal):
    assert cal.is_trading_day(date(2026, 7, 5)) is False


def test_holiday_is_not_trading_day(cal):
    assert cal.is_trading_day(date(2026, 1, 26)) is False  # Republic Day (Monday)
    assert cal.is_trading_day(date(2026, 12, 25)) is False  # Christmas (Friday)


def test_no_holidays_configured():
    cal = MarketCalendar({"trading": {"market_open": "09:15", "market_close": "15:30"}})
    assert cal.is_trading_day(date(2026, 7, 3)) is True


# ── is_market_open_now ────────────────────────────────────────────────────────

def test_open_during_market_hours(cal):
    assert cal.is_market_open_now(datetime(2026, 7, 3, 11, 0)) is True


def test_closed_before_open(cal):
    assert cal.is_market_open_now(datetime(2026, 7, 3, 9, 0)) is False


def test_closed_after_close(cal):
    assert cal.is_market_open_now(datetime(2026, 7, 3, 16, 0)) is False


def test_closed_on_holiday_even_during_hours(cal):
    assert cal.is_market_open_now(datetime(2026, 1, 26, 11, 0)) is False


def test_closed_on_weekend_even_during_hours(cal):
    assert cal.is_market_open_now(datetime(2026, 7, 4, 11, 0)) is False


def test_boundary_open_and_close_inclusive(cal):
    assert cal.is_market_open_now(datetime(2026, 7, 3, 9, 15)) is True
    assert cal.is_market_open_now(datetime(2026, 7, 3, 15, 30)) is True
