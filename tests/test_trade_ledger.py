import csv
from datetime import datetime

import pytest

from src.trade_ledger import TradeLedger


@pytest.fixture
def ledger(tmp_path):
    return TradeLedger(log_dir=str(tmp_path))


def _record(ledger, symbol="RELIANCE", direction="BUY", pnl=560.0, reason="target_hit"):
    ledger.record(
        symbol=symbol, direction=direction, quantity=10,
        entry_price=2800.0, exit_price=2856.0,
        entry_time=datetime(2026, 7, 3, 10, 15), exit_time=datetime(2026, 7, 3, 11, 30),
        pnl=pnl, exit_reason=reason,
    )


def test_record_creates_csv_with_header(ledger, tmp_path):
    _record(ledger)
    files = list(tmp_path.glob("trades_*.csv"))
    assert len(files) == 1
    with open(files[0], newline="") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["symbol", "direction", "quantity", "entry_price", "exit_price",
                       "entry_time", "exit_time", "pnl", "exit_reason"]
    assert rows[1][0] == "RELIANCE"


def test_record_appends_without_duplicate_header(ledger, tmp_path):
    _record(ledger)
    _record(ledger, symbol="TCS")
    files = list(tmp_path.glob("trades_*.csv"))
    with open(files[0], newline="") as f:
        rows = list(csv.reader(f))
    assert len(rows) == 3  # header + 2 trades
    assert rows[2][0] == "TCS"


def test_today_trades_reads_back_records(ledger):
    _record(ledger)
    _record(ledger, symbol="INFY", pnl=-150.0, reason="sl_hit")
    trades = ledger.today_trades()
    assert len(trades) == 2
    assert trades[0]["symbol"] == "RELIANCE"
    assert trades[1]["symbol"] == "INFY"
    assert float(trades[1]["pnl"]) == -150.0


def test_today_trades_empty_when_no_file(ledger):
    assert ledger.today_trades() == []


def test_format_summary_contains_trades(ledger):
    _record(ledger)
    _record(ledger, symbol="INFY", direction="SELL", pnl=-150.0, reason="sl_hit")
    summary = ledger.format_summary()
    assert "RELIANCE" in summary
    assert "+560.00" in summary
    assert "-150.00" in summary
    assert "sl_hit" in summary


def test_format_summary_none_when_no_trades(ledger):
    assert ledger.format_summary() is None


def test_pnl_rounded_to_two_decimals(ledger):
    ledger.record(
        symbol="X", direction="BUY", quantity=3,
        entry_price=100.123456, exit_price=101.987654,
        entry_time=datetime(2026, 7, 3, 10, 0), exit_time=datetime(2026, 7, 3, 11, 0),
        pnl=5.592594, exit_reason="target_hit",
    )
    t = ledger.today_trades()[0]
    assert t["pnl"] == "5.59"
    assert t["entry_price"] == "100.12"
