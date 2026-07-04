from datetime import datetime

import pytest

from src.trade_db import TradeDB


@pytest.fixture
def db(tmp_path):
    return TradeDB(path=str(tmp_path / "trades.db"))


def _trade(db, source="paper", symbol="RELIANCE", pnl=560.0):
    db.record_trade(
        source=source, strategy="momentum_vwap_breakout", symbol=symbol,
        direction="BUY", quantity=10, entry_price=2800.0, exit_price=2856.0,
        entry_time=datetime(2026, 7, 4, 10, 15), exit_time=datetime(2026, 7, 4, 11, 0),
        pnl=pnl, costs=45.0, exit_reason="target_hit",
    )


def test_schema_created(db):
    # reading empty tables should not raise
    assert db.trades() == []
    assert db.signals() == []


def test_record_and_read_trade(db):
    _trade(db)
    rows = db.trades()
    assert len(rows) == 1
    assert rows[0]["symbol"] == "RELIANCE"
    assert rows[0]["source"] == "paper"
    assert rows[0]["strategy"] == "momentum_vwap_breakout"
    assert rows[0]["pnl"] == 560.0
    assert rows[0]["costs"] == 45.0


def test_trades_filter_by_source(db):
    _trade(db, source="paper")
    _trade(db, source="live", symbol="TCS")
    _trade(db, source="backtest", symbol="INFY")
    assert len(db.trades()) == 3
    assert len(db.trades(source="live")) == 1
    assert db.trades(source="live")[0]["symbol"] == "TCS"


def test_record_signal_taken_and_skipped(db):
    db.record_signal(source="paper", symbol="RELIANCE", direction="BUY", taken=True)
    db.record_signal(source="paper", symbol="TCS", direction="SELL", taken=False,
                     reason="regime_mismatch")
    all_sig = db.signals()
    assert len(all_sig) == 2
    assert len(db.signals(taken=True)) == 1
    skipped = db.signals(taken=False)
    assert skipped[0]["reason"] == "regime_mismatch"


def test_record_scan_rankings(db):
    db.record_scan([
        {"symbol": "RELIANCE", "rank": 1, "score": 9.5, "rvol": 2.1, "pct_change": 1.8},
        {"symbol": "TCS", "rank": 2, "score": 8.1, "rvol": 1.7, "pct_change": 1.2},
    ])
    # read back via a direct connection
    with db._connect() as con:
        rows = [dict(r) for r in con.execute("SELECT * FROM scanner_rankings ORDER BY rank")]
    assert len(rows) == 2
    assert rows[0]["symbol"] == "RELIANCE"
    assert rows[0]["rvol"] == 2.1


def test_record_snapshot(db):
    db.record_snapshot(open_positions=2, daily_pnl=-1200.5, trades_today=4, regime="BULLISH")
    with db._connect() as con:
        rows = [dict(r) for r in con.execute("SELECT * FROM cycle_snapshots")]
    assert rows[0]["open_positions"] == 2
    assert rows[0]["regime"] == "BULLISH"
    assert rows[0]["daily_pnl"] == -1200.5


def test_record_scan_empty_is_noop(db):
    db.record_scan([])  # should not raise
    with db._connect() as con:
        assert con.execute("SELECT COUNT(*) FROM scanner_rankings").fetchone()[0] == 0


def test_accepts_string_times(db):
    db.record_trade(
        source="backtest", symbol="X", direction="SELL", quantity=1,
        entry_price=100.0, exit_price=98.0,
        entry_time="2026-07-04 10:00:00", exit_time="2026-07-04 10:30:00",
        pnl=2.0, exit_reason="target_hit",
    )
    assert db.trades()[0]["entry_time"] == "2026-07-04 10:00:00"
