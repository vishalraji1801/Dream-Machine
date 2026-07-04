from unittest.mock import MagicMock

import pandas as pd

from src.stock_selector import daily_metrics, rank_candidates, select_stocks


def _daily(close, vol, n=30, atr_spread=2.0):
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-06-01", periods=n, freq="D"),
        "open": [close] * n,
        "high": [close + atr_spread] * n,
        "low": [close - atr_spread] * n,
        "close": [close] * n,
        "volume": [vol] * n,
    })


# ── daily_metrics ─────────────────────────────────────────────────────────────

def test_daily_metrics_turnover_and_atr():
    m = daily_metrics(_daily(close=1000.0, vol=100000, atr_spread=20.0))
    assert m["avg_close"] == 1000.0
    assert m["avg_turnover"] == 1000.0 * 100000     # 10 crore
    assert m["atr_pct"] > 0                          # ~4% (range 40 / 1000)


# ── rank_candidates ───────────────────────────────────────────────────────────

def _cfg(**u):
    base = {"min_turnover_cr": 50, "atr_pct_min": 1.0, "atr_pct_max": 6.0,
            "price_min": 100, "price_max": 5000}
    base.update(u)
    return {"universe": base}


def test_rank_filters_low_turnover():
    metrics = {
        "BIG":   {"avg_close": 1000, "avg_turnover": 100e7, "atr_pct": 2.0},   # 100 cr
        "SMALL": {"avg_close": 1000, "avg_turnover": 10e7,  "atr_pct": 2.0},   # 10 cr < 50
    }
    assert rank_candidates(metrics, _cfg()) == ["BIG"]


def test_rank_filters_volatility_band():
    metrics = {
        "OK":    {"avg_close": 1000, "avg_turnover": 100e7, "atr_pct": 3.0},
        "FLAT":  {"avg_close": 1000, "avg_turnover": 100e7, "atr_pct": 0.3},   # < 1%
        "WILD":  {"avg_close": 1000, "avg_turnover": 100e7, "atr_pct": 9.0},   # > 6%
    }
    assert rank_candidates(metrics, _cfg()) == ["OK"]


def test_rank_filters_price_band():
    metrics = {
        "MID":    {"avg_close": 1000, "avg_turnover": 100e7, "atr_pct": 2.0},
        "PENNY":  {"avg_close": 40,   "avg_turnover": 100e7, "atr_pct": 2.0},
        "PRICEY": {"avg_close": 9000, "avg_turnover": 100e7, "atr_pct": 2.0},
    }
    assert rank_candidates(metrics, _cfg()) == ["MID"]


def test_rank_orders_by_turnover_desc():
    metrics = {
        "A": {"avg_close": 1000, "avg_turnover": 60e7,  "atr_pct": 2.0},
        "B": {"avg_close": 1000, "avg_turnover": 200e7, "atr_pct": 2.0},
        "C": {"avg_close": 1000, "avg_turnover": 120e7, "atr_pct": 2.0},
    }
    assert rank_candidates(metrics, _cfg()) == ["B", "C", "A"]


# ── select_stocks ─────────────────────────────────────────────────────────────

def test_select_stocks_ranks_and_caps():
    kite = MagicMock()
    kite.instruments.return_value = [
        {"tradingsymbol": s, "instrument_token": i, "instrument_type": "EQ"}
        for i, s in enumerate(["RELIANCE", "TCS", "INFY"], 1)
    ]
    # RELIANCE most liquid, INFY least
    vols = {"RELIANCE": 500000, "TCS": 300000, "INFY": 120000}

    def fake_daily(k, token, days):
        sym = {1: "RELIANCE", 2: "TCS", 3: "INFY"}[token]
        return _daily(close=1000.0, vol=vols[sym], atr_spread=20.0)

    cfg = {"trading": {"exchange": "NSE", "watchlist": ["RELIANCE", "TCS", "INFY"]},
           "universe": {"min_turnover_cr": 5, "atr_pct_min": 1.0, "atr_pct_max": 6.0,
                        "price_min": 100, "price_max": 5000}}
    stocks = select_stocks(kite, cfg, num_stocks=2, daily_fetch=fake_daily)
    assert [s["symbol"] for s in stocks] == ["RELIANCE", "TCS"]   # top-2 by turnover
    assert stocks[0]["token"] == 1


def test_select_stocks_skips_thin_history():
    kite = MagicMock()
    kite.instruments.return_value = [
        {"tradingsymbol": "RELIANCE", "instrument_token": 1, "instrument_type": "EQ"}]

    def short_daily(k, token, days):
        return _daily(close=1000.0, vol=500000, n=5)   # < 15 rows -> skipped

    cfg = {"trading": {"exchange": "NSE", "watchlist": ["RELIANCE"]},
           "universe": {"min_turnover_cr": 5}}
    assert select_stocks(kite, cfg, 10, daily_fetch=short_daily) == []


def test_select_stocks_uses_fno_pool_when_set():
    kite = MagicMock()
    kite.instruments.return_value = [
        {"tradingsymbol": s, "instrument_token": i, "instrument_type": "EQ"}
        for i, s in enumerate(["RELIANCE", "TCS", "ZEEL"], 1)
    ]
    seen = []

    def fake_daily(k, token, days):
        seen.append(token)
        return _daily(close=1000.0, vol=500000, atr_spread=20.0)

    cfg = {"trading": {"exchange": "NSE", "watchlist": ["RELIANCE", "TCS", "ZEEL"]},
           "universe": {"fno_underlyings": ["TCS"], "min_turnover_cr": 5,
                        "atr_pct_min": 1.0, "atr_pct_max": 6.0,
                        "price_min": 100, "price_max": 5000}}
    stocks = select_stocks(kite, cfg, 10, daily_fetch=fake_daily)
    assert [s["symbol"] for s in stocks] == ["TCS"]   # only the fno pool considered
    assert seen == [2]                                # only TCS's token fetched
