from unittest.mock import MagicMock
import pytest

from src.paper_trader import PaperTrader


@pytest.fixture
def cfg():
    return {
        "trading": {"exchange": "NSE"},
        "paper_trading": {"enabled": True, "simulated_slippage_pct": 0.05},
    }


@pytest.fixture
def fetcher():
    m = MagicMock()
    m.get_quotes.return_value = {"RELIANCE": {"ltp": 2850.0}}
    return m


@pytest.fixture
def pt(fetcher, cfg):
    return PaperTrader(fetcher, cfg)


# ── place_order ───────────────────────────────────────────────────────────────

def test_place_order_returns_paper_prefixed_id(pt):
    oid = pt.place_order("RELIANCE", "BUY", 10, 2850.0, "LIMIT")
    assert oid.startswith("PAPER-")


def test_place_order_ids_are_sequential(pt):
    id1 = pt.place_order("RELIANCE", "BUY", 10, 2850.0)
    id2 = pt.place_order("TCS", "SELL", 5, 3500.0)
    assert id1 != id2
    assert int(id1.split("-")[1]) < int(id2.split("-")[1])


def test_limit_buy_fills_at_price_plus_slippage(pt):
    oid = pt.place_order("RELIANCE", "BUY", 10, 2850.0, "LIMIT")
    result = pt.monitor_order(oid)
    expected = round(2850.0 * 1.0005, 2)
    assert result["average_price"] == expected


def test_limit_sell_fills_at_price_minus_slippage(pt):
    oid = pt.place_order("RELIANCE", "SELL", 10, 2850.0, "LIMIT")
    result = pt.monitor_order(oid)
    expected = round(2850.0 * 0.9995, 2)
    assert result["average_price"] == expected


def test_market_buy_fills_at_ltp_plus_slippage(pt, fetcher):
    fetcher.get_quotes.return_value = {"RELIANCE": {"ltp": 2860.0}}
    oid = pt.place_order("RELIANCE", "BUY", 10, 0.0, "MARKET")
    result = pt.monitor_order(oid)
    expected = round(2860.0 * 1.0005, 2)
    assert result["average_price"] == expected


def test_market_sell_fills_at_ltp_minus_slippage(pt, fetcher):
    fetcher.get_quotes.return_value = {"RELIANCE": {"ltp": 2860.0}}
    oid = pt.place_order("RELIANCE", "SELL", 10, 0.0, "MARKET")
    result = pt.monitor_order(oid)
    expected = round(2860.0 * 0.9995, 2)
    assert result["average_price"] == expected


def test_market_order_falls_back_to_price_when_no_quote(pt, fetcher):
    fetcher.get_quotes.return_value = None
    oid = pt.place_order("RELIANCE", "BUY", 10, 2850.0, "MARKET")
    result = pt.monitor_order(oid)
    assert result["average_price"] == round(2850.0 * 1.0005, 2)


def test_place_order_status_is_complete(pt):
    oid = pt.place_order("RELIANCE", "BUY", 10, 2850.0)
    result = pt.monitor_order(oid)
    assert result["status"] == "COMPLETE"


def test_place_order_filled_quantity_matches(pt):
    oid = pt.place_order("RELIANCE", "BUY", 7, 2850.0)
    result = pt.monitor_order(oid)
    assert result["filled_quantity"] == 7


def test_zero_slippage_config(fetcher):
    cfg = {"trading": {"exchange": "NSE"}, "paper_trading": {"simulated_slippage_pct": 0.0}}
    pt = PaperTrader(fetcher, cfg)
    oid = pt.place_order("RELIANCE", "BUY", 10, 2850.0, "LIMIT")
    result = pt.monitor_order(oid)
    assert result["average_price"] == 2850.0


# ── monitor_order / get_order_status ─────────────────────────────────────────

def test_monitor_order_returns_immediately(pt):
    oid = pt.place_order("RELIANCE", "BUY", 10, 2850.0)
    assert pt.monitor_order(oid) is not None


def test_monitor_unknown_order_returns_none(pt):
    assert pt.monitor_order("PAPER-999999") is None


def test_get_order_status_matches_monitor_order(pt):
    oid = pt.place_order("RELIANCE", "BUY", 10, 2850.0)
    assert pt.get_order_status(oid) == pt.monitor_order(oid)


# ── cancel_order ──────────────────────────────────────────────────────────────

def test_cancel_order_always_returns_true(pt):
    oid = pt.place_order("RELIANCE", "BUY", 10, 2850.0)
    assert pt.cancel_order(oid) is True


def test_cancel_unknown_order_returns_true(pt):
    assert pt.cancel_order("PAPER-000000") is True


# ── Realistic fills ───────────────────────────────────────────────────────────

@pytest.fixture
def realistic_pt(fetcher):
    cfg = {
        "trading": {"exchange": "NSE"},
        "paper_trading": {"enabled": True, "simulated_slippage_pct": 0.05,
                          "realistic_fills": True},
    }
    return PaperTrader(fetcher, cfg)


def test_realistic_buy_limit_fills_when_ltp_at_or_below_limit(realistic_pt, fetcher):
    fetcher.get_quotes.return_value = {"RELIANCE": {"ltp": 2848.0}}
    oid = realistic_pt.place_order("RELIANCE", "BUY", 10, 2850.0, "LIMIT")
    assert realistic_pt.monitor_order(oid)["status"] == "COMPLETE"


def test_realistic_buy_limit_stays_open_when_ltp_above_limit(realistic_pt, fetcher):
    fetcher.get_quotes.return_value = {"RELIANCE": {"ltp": 2855.0}}
    oid = realistic_pt.place_order("RELIANCE", "BUY", 10, 2850.0, "LIMIT")
    result = realistic_pt.monitor_order(oid)
    assert result["status"] == "OPEN"
    assert result["filled_quantity"] == 0
    assert result["pending_quantity"] == 10


def test_realistic_sell_limit_fills_when_ltp_at_or_above_limit(realistic_pt, fetcher):
    fetcher.get_quotes.return_value = {"TCS": {"ltp": 3505.0}}
    oid = realistic_pt.place_order("TCS", "SELL", 5, 3500.0, "LIMIT")
    assert realistic_pt.monitor_order(oid)["status"] == "COMPLETE"


def test_realistic_sell_limit_stays_open_when_ltp_below_limit(realistic_pt, fetcher):
    fetcher.get_quotes.return_value = {"TCS": {"ltp": 3490.0}}
    oid = realistic_pt.place_order("TCS", "SELL", 5, 3500.0, "LIMIT")
    assert realistic_pt.monitor_order(oid)["status"] == "OPEN"


def test_realistic_market_order_always_fills(realistic_pt, fetcher):
    fetcher.get_quotes.return_value = {"RELIANCE": {"ltp": 2855.0}}
    oid = realistic_pt.place_order("RELIANCE", "BUY", 10, 2850.0, "MARKET")
    result = realistic_pt.monitor_order(oid)
    assert result["status"] == "COMPLETE"
    assert result["average_price"] == round(2855.0 * 1.0005, 2)


def test_realistic_limit_fills_when_no_quote_available(realistic_pt, fetcher):
    fetcher.get_quotes.return_value = None
    oid = realistic_pt.place_order("RELIANCE", "BUY", 10, 2850.0, "LIMIT")
    assert realistic_pt.monitor_order(oid)["status"] == "COMPLETE"


def test_cancel_open_order_marks_cancelled(realistic_pt, fetcher):
    fetcher.get_quotes.return_value = {"RELIANCE": {"ltp": 2855.0}}
    oid = realistic_pt.place_order("RELIANCE", "BUY", 10, 2850.0, "LIMIT")
    assert realistic_pt.cancel_order(oid) is True
    result = realistic_pt.get_order_status(oid)
    assert result["status"] == "CANCELLED"
    assert result["pending_quantity"] == 0


def test_cancel_complete_order_does_not_change_status(realistic_pt, fetcher):
    fetcher.get_quotes.return_value = {"RELIANCE": {"ltp": 2848.0}}
    oid = realistic_pt.place_order("RELIANCE", "BUY", 10, 2850.0, "LIMIT")
    realistic_pt.cancel_order(oid)
    assert realistic_pt.get_order_status(oid)["status"] == "COMPLETE"


def test_default_mode_fills_even_when_ltp_above_limit(pt, fetcher):
    # realistic_fills defaults to False — old optimistic behavior preserved
    fetcher.get_quotes.return_value = {"RELIANCE": {"ltp": 2855.0}}
    oid = pt.place_order("RELIANCE", "BUY", 10, 2850.0, "LIMIT")
    assert pt.monitor_order(oid)["status"] == "COMPLETE"


# ── GTT OCO ───────────────────────────────────────────────────────────────────

def test_place_gtt_oco_returns_integer_id(pt):
    gtt_id = pt.place_gtt_oco("RELIANCE", "BUY", 10, 2772.0, 2856.0, 2814.0)
    assert isinstance(gtt_id, int)


def test_place_gtt_oco_ids_are_sequential(pt):
    id1 = pt.place_gtt_oco("RELIANCE", "BUY", 10, 2772.0, 2856.0, 2814.0)
    id2 = pt.place_gtt_oco("TCS", "SELL", 5, 3550.0, 3450.0, 3500.0)
    assert id2 == id1 + 1


def test_cancel_gtt_always_returns_true(pt):
    gtt_id = pt.place_gtt_oco("RELIANCE", "BUY", 10, 2772.0, 2856.0, 2814.0)
    assert pt.cancel_gtt(gtt_id) is True


def test_cancel_unknown_gtt_returns_true(pt):
    assert pt.cancel_gtt(9999) is True
