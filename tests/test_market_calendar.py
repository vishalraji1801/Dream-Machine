from datetime import date, datetime

import pytest

from src.market_calendar import MarketCalendar


@pytest.fixture
def cal():
    cfg = {"trading": {"market_open": "09:15", "market_close": "15:30"}}
    return MarketCalendar(cfg)


# ── is_trading_day ────────────────────────────────────────────────────────────

def test_weekday_is_trading_day(cal):
    assert cal.is_trading_day(date(2026, 7, 3)) is True  # Friday


def test_saturday_is_not_trading_day(cal):
    assert cal.is_trading_day(date(2026, 7, 4)) is False


def test_sunday_is_not_trading_day(cal):
    assert cal.is_trading_day(date(2026, 7, 5)) is False


# ── is_market_open_now ────────────────────────────────────────────────────────

def test_open_during_market_hours(cal):
    assert cal.is_market_open_now(datetime(2026, 7, 3, 11, 0)) is True


def test_closed_before_open(cal):
    assert cal.is_market_open_now(datetime(2026, 7, 3, 9, 0)) is False


def test_closed_after_close(cal):
    assert cal.is_market_open_now(datetime(2026, 7, 3, 16, 0)) is False


def test_closed_on_weekend_even_during_hours(cal):
    assert cal.is_market_open_now(datetime(2026, 7, 4, 11, 0)) is False


def test_boundary_open_and_close_inclusive(cal):
    assert cal.is_market_open_now(datetime(2026, 7, 3, 9, 15)) is True
    assert cal.is_market_open_now(datetime(2026, 7, 3, 15, 30)) is True


def test_status_text_open(cal):
    import unittest.mock as m
    with m.patch("src.market_calendar.datetime") as dt:
        dt.now.return_value = datetime(2026, 7, 3, 11, 0)
        assert cal.status_text() == "OPEN"


def test_status_text_weekend(cal):
    import unittest.mock as m
    with m.patch("src.market_calendar.datetime") as dt:
        dt.now.return_value = datetime(2026, 7, 4, 11, 0)
        assert cal.status_text() == "CLOSED (weekend)"
