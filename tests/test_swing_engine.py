"""Swing engine — daily donchian/bb entries, overnight state, exits."""
from datetime import datetime

import pandas as pd
import pytest
import yaml

from src.swing_engine import SwingEngine


def _daily(closes, highs=None, lows=None):
    n = len(closes)
    return pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n, freq="D"),
        "open": closes,
        "high": highs if highs is not None else [c + 2 for c in closes],
        "low": lows if lows is not None else [c - 2 for c in closes],
        "close": closes, "volume": [1_000_000] * n})


def _cfg():
    c = yaml.safe_load(open("config/config.yaml", encoding="utf-8"))
    c["trading"]["watchlist"] = ["AAA", "BBB"]
    c["swing"]["capital"] = 1_000_000
    return c


class FakeDB:
    def __init__(self):
        self.trades, self.signals, self.routing = [], [], []

    def record_trade(self, **k): self.trades.append(k)
    def record_signal(self, **k): self.signals.append(k)
    def record_routing(self, **k): self.routing.append(k)


def _fetch(data):
    return lambda s, d: data.get(s)


NOW = datetime(2026, 7, 14, 15, 5)


def test_enters_donchian_long_in_uptrend(tmp_path):
    up = _daily([100 + i for i in range(260)])            # index: strong uptrend
    stock = _daily([100 + i * 0.8 for i in range(260)])   # new 200-day high on last bar
    data = {"NIFTY 50": up, "AAA": stock, "BBB": _daily([200] * 260)}
    db = FakeDB()
    eng = SwingEngine(_cfg(), "paper", db, _fetch(data), state_path=str(tmp_path / "sw.json"))
    r = eng.run_daily(now=NOW)
    assert r["regime"] == "STRONG_TREND_UP"
    assert "AAA" in eng.positions
    pos = eng.positions["AAA"]
    assert pos.strategy == "donchian_trend_tsl" and pos.direction == "BUY"
    assert pos.stop < pos.entry_price
    assert db.signals and db.routing                      # persisted


def test_state_persists_across_restart(tmp_path):
    up = _daily([100 + i for i in range(260)])
    stock = _daily([100 + i * 0.8 for i in range(260)])
    data = {"NIFTY 50": up, "AAA": stock, "BBB": _daily([200] * 260)}
    sp = str(tmp_path / "sw.json")
    SwingEngine(_cfg(), "paper", FakeDB(), _fetch(data), state_path=sp).run_daily(now=NOW)
    reloaded = SwingEngine(_cfg(), "paper", FakeDB(), _fetch(data), state_path=sp)
    assert "AAA" in reloaded.positions                    # survived the "restart"


def test_exit_on_trailing_stop(tmp_path):
    up = _daily([100 + i for i in range(260)])
    stock = _daily([100 + i * 0.8 for i in range(260)])
    data = {"NIFTY 50": up, "AAA": stock, "BBB": _daily([200] * 260)}
    db = FakeDB()
    eng = SwingEngine(_cfg(), "paper", db, _fetch(data), state_path=str(tmp_path / "sw.json"))
    eng.run_daily(now=NOW)
    assert "AAA" in eng.positions
    stop = eng.positions["AAA"].stop
    # next day: AAA craters below the stop -> the trailing stop must exit the long.
    crash = [100 + i * 0.8 for i in range(259)] + [stop - 20]
    data["AAA"] = _daily(crash, lows=[c - 2 for c in crash[:-1]] + [stop - 25])
    eng.run_daily(now=datetime(2026, 7, 15, 15, 5))
    # The trailing stop exited the original donchian long. A dip-buy / other strategy
    # may re-enter AAA the SAME cycle (separate, valid decision) now that the sleeve
    # holds 6 strategies — so assert the EXIT fired, not permanent absence.
    assert any(t["exit_reason"].startswith("swing_stop") for t in db.trades)
    held = eng.positions.get("AAA")
    assert held is None or held.entry_date != NOW.date().isoformat()   # original long gone


def test_winners_are_regime_agnostic(tmp_path):
    # The maker/gauntlet winners are validated regime-OFF, so they trade a trending stock
    # even when the INDEX is non-trend (the retired manual set used to sit out here). This
    # is the intended behavior change from wiring the OOS-validated basket.
    flat = _daily([200 + (1 if i % 2 else -1) for i in range(260)])   # index oscillates
    stock = _daily([100 + i * 0.8 for i in range(260)])               # AAA trends -> fires
    data = {"NIFTY 50": flat, "AAA": stock, "BBB": _daily([200] * 260)}
    eng = SwingEngine(_cfg(), "paper", FakeDB(), _fetch(data), state_path=str(tmp_path / "sw.json"))
    r = eng.run_daily(now=NOW)
    assert r["regime"] not in ("STRONG_TREND_UP", "STRONG_TREND_DOWN")   # non-trend index
    assert any(p.symbol == "AAA" for p in eng.positions.values())        # winner still trades it


def test_insufficient_index_data_skips(tmp_path):
    data = {"NIFTY 50": _daily([100] * 20)}
    eng = SwingEngine(_cfg(), "paper", FakeDB(), _fetch(data), state_path=str(tmp_path / "sw.json"))
    r = eng.run_daily(now=NOW)
    assert r["regime"] == "UNKNOWN" and r["entered"] == 0
