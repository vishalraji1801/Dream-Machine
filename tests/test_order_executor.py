from unittest.mock import MagicMock, patch, call

import pytest
from kiteconnect import exceptions as kite_exc

from src.order_executor import OrderExecutor


@pytest.fixture
def cfg():
    return {
        "trading": {
            "exchange": "NSE",
            "product_type": "MIS",
        }
    }


@pytest.fixture
def mock_kite():
    return MagicMock()


@pytest.fixture
def executor(mock_kite, cfg):
    return OrderExecutor(mock_kite, cfg)


def _order_history(status, avg_price=2850.0, filled=10, pending=0, message=None):
    return [
        {
            "status": status,
            "average_price": avg_price,
            "filled_quantity": filled,
            "pending_quantity": pending,
            "status_message": message,
        }
    ]


# ── place_order ───────────────────────────────────────────────────────────────

def test_place_order_returns_order_id(executor, mock_kite):
    mock_kite.place_order.return_value = "231223000001"
    oid = executor.place_order("RELIANCE", "BUY", 10, 2850.0)
    assert oid == "231223000001"


def test_place_order_calls_kite_with_correct_params(executor, mock_kite):
    mock_kite.place_order.return_value = "999"
    executor.place_order("TCS", "BUY", 5, 3500.0, "LIMIT")
    mock_kite.place_order.assert_called_once_with(
        variety="regular",
        exchange="NSE",
        tradingsymbol="TCS",
        transaction_type="BUY",
        quantity=5,
        price=3500.0,
        product="MIS",
        order_type="LIMIT",
    )


def test_place_order_market_sends_zero_price(executor, mock_kite):
    mock_kite.place_order.return_value = "888"
    executor.place_order("INFY", "SELL", 3, 1500.0, "MARKET")
    _, kwargs = mock_kite.place_order.call_args
    assert kwargs["price"] == 0
    assert kwargs["order_type"] == "MARKET"


def test_place_order_returns_none_on_order_exception(executor, mock_kite):
    mock_kite.place_order.side_effect = kite_exc.OrderException("Insufficient funds")
    assert executor.place_order("RELIANCE", "BUY", 10, 2850.0) is None


def test_place_order_returns_none_on_input_exception(executor, mock_kite):
    mock_kite.place_order.side_effect = kite_exc.InputException("Invalid quantity")
    assert executor.place_order("RELIANCE", "BUY", -1, 2850.0) is None


def test_place_order_returns_none_on_unexpected_error(executor, mock_kite):
    mock_kite.place_order.side_effect = Exception("Network error")
    assert executor.place_order("RELIANCE", "BUY", 10, 2850.0) is None


def test_place_order_sell_direction(executor, mock_kite):
    mock_kite.place_order.return_value = "777"
    oid = executor.place_order("TCS", "SELL", 5, 3500.0)
    assert oid == "777"
    _, kwargs = mock_kite.place_order.call_args
    assert kwargs["transaction_type"] == "SELL"


# ── get_order_status ──────────────────────────────────────────────────────────

def test_get_order_status_returns_normalised_dict(executor, mock_kite):
    mock_kite.order_history.return_value = _order_history("COMPLETE", avg_price=2853.0, filled=10)
    status = executor.get_order_status("231223000001")
    assert status["status"] == "COMPLETE"
    assert status["average_price"] == 2853.0
    assert status["filled_quantity"] == 10
    assert status["order_id"] == "231223000001"


def test_get_order_status_uses_latest_history_entry(executor, mock_kite):
    mock_kite.order_history.return_value = [
        {"status": "OPEN", "average_price": 0.0, "filled_quantity": 0, "pending_quantity": 10, "status_message": None},
        {"status": "COMPLETE", "average_price": 2850.0, "filled_quantity": 10, "pending_quantity": 0, "status_message": None},
    ]
    status = executor.get_order_status("abc")
    assert status["status"] == "COMPLETE"


def test_get_order_status_returns_none_on_empty_history(executor, mock_kite):
    mock_kite.order_history.return_value = []
    assert executor.get_order_status("abc") is None


def test_get_order_status_returns_none_on_api_error(executor, mock_kite):
    mock_kite.order_history.side_effect = Exception("API error")
    assert executor.get_order_status("abc") is None


# ── monitor_order ─────────────────────────────────────────────────────────────

def test_monitor_order_returns_complete_immediately(executor, mock_kite):
    mock_kite.order_history.return_value = _order_history("COMPLETE", avg_price=2850.0, filled=10)
    with patch("src.order_executor.time.sleep"):
        result = executor.monitor_order("123")
    assert result["status"] == "COMPLETE"
    assert result["average_price"] == 2850.0


def test_monitor_order_polls_until_complete(executor, mock_kite):
    mock_kite.order_history.side_effect = [
        _order_history("OPEN", filled=0, pending=10),
        _order_history("OPEN", filled=0, pending=10),
        _order_history("COMPLETE", avg_price=2855.0, filled=10, pending=0),
    ]
    with patch("src.order_executor.time.sleep") as mock_sleep:
        result = executor.monitor_order("123")
    assert result["status"] == "COMPLETE"
    assert mock_kite.order_history.call_count == 3
    assert mock_sleep.call_count == 2


def test_monitor_order_returns_rejected(executor, mock_kite):
    mock_kite.order_history.return_value = _order_history(
        "REJECTED", message="RMS: Margin shortfall"
    )
    with patch("src.order_executor.time.sleep"):
        result = executor.monitor_order("123")
    assert result["status"] == "REJECTED"
    assert result["status_message"] == "RMS: Margin shortfall"


def test_monitor_order_returns_cancelled(executor, mock_kite):
    mock_kite.order_history.return_value = _order_history("CANCELLED")
    with patch("src.order_executor.time.sleep"):
        result = executor.monitor_order("123")
    assert result["status"] == "CANCELLED"


def test_monitor_order_returns_none_on_timeout(executor, mock_kite):
    mock_kite.order_history.return_value = _order_history("OPEN", filled=0, pending=10)
    with patch("src.order_executor.time.monotonic") as mock_time, \
         patch("src.order_executor.time.sleep"):
        mock_time.side_effect = [0, 0, 61]  # start, first check, timeout
        result = executor.monitor_order("123", timeout_sec=60)
    assert result is None


def test_monitor_order_returns_none_on_status_api_error(executor, mock_kite):
    mock_kite.order_history.side_effect = Exception("API error")
    with patch("src.order_executor.time.sleep"):
        result = executor.monitor_order("123", timeout_sec=10)
    assert result is None


# ── cancel_order ──────────────────────────────────────────────────────────────

def test_cancel_order_returns_true_on_success(executor, mock_kite):
    mock_kite.cancel_order.return_value = {"order_id": "123"}
    assert executor.cancel_order("123") is True


def test_cancel_order_calls_kite_with_correct_params(executor, mock_kite):
    mock_kite.cancel_order.return_value = {}
    executor.cancel_order("456")
    mock_kite.cancel_order.assert_called_once_with(variety="regular", order_id="456")


def test_cancel_order_returns_false_on_order_exception(executor, mock_kite):
    mock_kite.cancel_order.side_effect = kite_exc.OrderException("Order already complete")
    assert executor.cancel_order("123") is False


def test_cancel_order_returns_false_on_input_exception(executor, mock_kite):
    mock_kite.cancel_order.side_effect = kite_exc.InputException("Invalid order id")
    assert executor.cancel_order("bad_id") is False


def test_cancel_order_returns_false_on_unexpected_error(executor, mock_kite):
    mock_kite.cancel_order.side_effect = Exception("Network error")
    assert executor.cancel_order("123") is False


# ── place_gtt_oco ─────────────────────────────────────────────────────────────

def test_place_gtt_oco_buy_returns_trigger_id(executor, mock_kite):
    mock_kite.place_gtt.return_value = {"trigger_id": 99}
    gtt_id = executor.place_gtt_oco("RELIANCE", "BUY", 10, 2772.0, 2856.0, 2814.0)
    assert gtt_id == 99


def test_place_gtt_oco_buy_uses_two_leg_trigger_type(executor, mock_kite):
    mock_kite.place_gtt.return_value = {"trigger_id": 1}
    executor.place_gtt_oco("RELIANCE", "BUY", 10, 2772.0, 2856.0, 2814.0)
    _, kwargs = mock_kite.place_gtt.call_args
    assert kwargs["trigger_type"] == "two-leg"


def test_place_gtt_oco_buy_trigger_values_sl_then_target(executor, mock_kite):
    mock_kite.place_gtt.return_value = {"trigger_id": 1}
    executor.place_gtt_oco("RELIANCE", "BUY", 10, 2772.0, 2856.0, 2814.0)
    _, kwargs = mock_kite.place_gtt.call_args
    assert kwargs["trigger_values"] == [2772.0, 2856.0]


def test_place_gtt_oco_sell_trigger_values_target_then_sl(executor, mock_kite):
    mock_kite.place_gtt.return_value = {"trigger_id": 2}
    executor.place_gtt_oco("RELIANCE", "SELL", 10, 2856.0, 2772.0, 2814.0)
    _, kwargs = mock_kite.place_gtt.call_args
    assert kwargs["trigger_values"] == [2772.0, 2856.0]


def test_place_gtt_oco_exit_is_sell_for_buy(executor, mock_kite):
    mock_kite.place_gtt.return_value = {"trigger_id": 3}
    executor.place_gtt_oco("RELIANCE", "BUY", 10, 2772.0, 2856.0, 2814.0)
    _, kwargs = mock_kite.place_gtt.call_args
    assert all(o["transaction_type"] == "SELL" for o in kwargs["orders"])


def test_place_gtt_oco_exit_is_buy_for_sell(executor, mock_kite):
    mock_kite.place_gtt.return_value = {"trigger_id": 4}
    executor.place_gtt_oco("RELIANCE", "SELL", 10, 2856.0, 2772.0, 2814.0)
    _, kwargs = mock_kite.place_gtt.call_args
    assert all(o["transaction_type"] == "BUY" for o in kwargs["orders"])


def test_place_gtt_oco_returns_none_on_error(executor, mock_kite):
    mock_kite.place_gtt.side_effect = Exception("API error")
    assert executor.place_gtt_oco("RELIANCE", "BUY", 10, 2772.0, 2856.0, 2814.0) is None


# ── cancel_gtt ────────────────────────────────────────────────────────────────

def test_cancel_gtt_returns_true_on_success(executor, mock_kite):
    mock_kite.cancel_gtt.return_value = {}
    assert executor.cancel_gtt(99) is True


def test_cancel_gtt_calls_kite_with_gtt_id(executor, mock_kite):
    mock_kite.cancel_gtt.return_value = {}
    executor.cancel_gtt(42)
    mock_kite.cancel_gtt.assert_called_once_with(42)


def test_cancel_gtt_returns_false_on_error(executor, mock_kite):
    mock_kite.cancel_gtt.side_effect = Exception("not found")
    assert executor.cancel_gtt(99) is False
