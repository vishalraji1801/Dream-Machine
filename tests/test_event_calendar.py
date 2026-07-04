from datetime import date

import yaml

from src.event_calendar import EventCalendar


def _cal(tmp_path, data=None):
    path = tmp_path / "events.yaml"
    if data is not None:
        path.write_text(yaml.safe_dump(data))
    return EventCalendar({"events": {"path": str(path)}})


def test_no_file_blocks_nothing(tmp_path):
    cal = _cal(tmp_path)
    assert cal.is_market_event_day(date(2026, 7, 6)) is False
    assert cal.symbol_has_event("RELIANCE", date(2026, 7, 6)) is False


def test_market_event_day_blocks(tmp_path):
    cal = _cal(tmp_path, {"market_event_days": ["2026-07-31"]})
    assert cal.is_market_event_day(date(2026, 7, 31)) is True
    assert cal.is_market_event_day(date(2026, 7, 30)) is False


def test_symbol_earnings_day(tmp_path):
    cal = _cal(tmp_path, {"earnings": {"RELIANCE": ["2026-07-18"]}})
    assert cal.symbol_has_event("RELIANCE", date(2026, 7, 18)) is True
    assert cal.symbol_has_event("RELIANCE", date(2026, 7, 19)) is False
    assert cal.symbol_has_event("TCS", date(2026, 7, 18)) is False


def test_empty_sections(tmp_path):
    cal = _cal(tmp_path, {"market_event_days": [], "earnings": {}})
    assert cal.is_market_event_day(date(2026, 7, 6)) is False


def test_corrupt_file_is_safe(tmp_path):
    path = tmp_path / "events.yaml"
    path.write_text("{bad: yaml: here")
    cal = EventCalendar({"events": {"path": str(path)}})
    assert cal.is_market_event_day(date(2026, 7, 6)) is False
