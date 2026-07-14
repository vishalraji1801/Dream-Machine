from unittest.mock import MagicMock, patch

import pytest

from src.alert_manager import AlertManager, _TEMPLATES


@pytest.fixture
def alert():
    return AlertManager(bot_token="dummy_token", chat_id="123456789")


def _mock_post_ok():
    mock = MagicMock()
    mock.raise_for_status = MagicMock()
    return mock


def test_send_order_placed(alert):
    with patch("src.alert_manager.requests.post", return_value=_mock_post_ok()) as mp:
        result = alert.send("order_placed", direction="BUY", symbol="RELIANCE",
                            qty=5, price=2845.50, order_type="LIMIT",
                            sl=2817.0, target=2902.5, order_id="1234567890")
        assert result is True
        mp.assert_called_once()
        payload = mp.call_args.kwargs["json"]
        assert "BUY" in payload["text"]
        assert "RELIANCE" in payload["text"]
        assert "LIMIT" in payload["text"]     # order type visible
        assert "SL: 2817.0" in payload["text"]


def test_mode_tag_prefixes_every_message():
    alert = AlertManager("tok", "cid", tag="PAPER")
    with patch("src.alert_manager.requests.post", return_value=_mock_post_ok()) as mp:
        alert.send_raw("hello")
    assert mp.call_args.kwargs["json"]["text"] == "[PAPER] hello"


def test_no_tag_by_default(alert):
    with patch("src.alert_manager.requests.post", return_value=_mock_post_ok()) as mp:
        alert.send_raw("hello")
    assert mp.call_args.kwargs["json"]["text"] == "hello"


def test_send_unknown_event_returns_false(alert):
    assert alert.send("not_a_real_event") is False


def test_send_missing_template_key_returns_false(alert):
    result = alert.send("order_placed", direction="BUY")
    assert result is False


def test_network_failure_returns_false(alert):
    import requests as req
    with patch("src.alert_manager.requests.post", side_effect=req.exceptions.ConnectionError("timeout")):
        assert alert.send("bot_started", minutes=10) is False


def test_all_event_templates_render():
    event_kwargs = {
        "bot_started":       {"minutes": 10},
        "order_placed":      {"direction": "BUY", "symbol": "TCS", "qty": 2, "price": 3500.0,
                              "order_type": "LIMIT", "sl": 3465.0, "target": 3570.0, "order_id": "ABC"},
        "order_filled":      {"symbol": "TCS", "actual_price": 3502.0, "slippage": 2.0},
        "order_rejected":    {"symbol": "TCS", "reason": "Insufficient funds"},
        "sl_hit":            {"symbol": "TCS", "entry": 3500.0, "exit_price": 3465.0, "loss": 70.0},
        "target_hit":        {"symbol": "TCS", "entry": 3500.0, "exit_price": 3570.0, "profit": 140.0},
        "circuit_breaker":   {"reason": "Daily loss limit"},
        "critical_error":    {"module": "strategy", "message": "Unexpected error"},
        "daily_summary":     {"trades": 3, "profit": 5000, "loss": 2000, "net_pnl": 3000},
        "signal_generated":  {"direction": "BUY", "symbol": "TCS", "entry": 3500.0, "sl": 3465.0,
                              "target": 3570.0, "action": "ENTERING"},
        "order_partial":     {"symbol": "TCS", "filled": 4, "requested": 10, "actual_price": 3501.0},
        "bot_stopped":       {"reason": "keyboard interrupt"},
        "api_error":         {"module": "data_fetcher", "message": "Timeout"},
    }
    with patch("src.alert_manager.requests.post", return_value=_mock_post_ok()):
        alert = AlertManager("tok", "cid")
        for event, kwargs in event_kwargs.items():
            assert alert.send(event, **kwargs) is True, f"Failed for event: {event}"


def test_all_templates_defined():
    expected = {
        "bot_started", "order_placed", "order_filled", "order_rejected",
        "sl_hit", "target_hit", "circuit_breaker", "critical_error", "daily_summary",
        "signal_generated", "bot_stopped", "api_error", "order_partial",
    }
    assert expected == set(_TEMPLATES.keys())


def test_signal_generated_contains_symbol_and_direction(alert):
    with patch("src.alert_manager.requests.post", return_value=_mock_post_ok()) as mp:
        alert.send("signal_generated", direction="SELL", symbol="INFY",
                   entry=1500.0, sl=1515.0, target=1470.0,
                   action="SKIPPED: margin 0 < threshold 25000")
    text = mp.call_args.kwargs["json"]["text"]
    assert "SELL" in text and "INFY" in text


def test_bot_stopped_contains_reason(alert):
    with patch("src.alert_manager.requests.post", return_value=_mock_post_ok()) as mp:
        alert.send("bot_stopped", reason="/stop command from Telegram")
    text = mp.call_args.kwargs["json"]["text"]
    assert "OFFLINE" in text
    assert "/stop command from Telegram" in text


def test_api_error_contains_module_and_message(alert):
    with patch("src.alert_manager.requests.post", return_value=_mock_post_ok()) as mp:
        alert.send("api_error", module="order_executor", message="Connection refused")
    text = mp.call_args.kwargs["json"]["text"]
    assert "order_executor" in text and "Connection refused" in text


def test_send_raw(alert):
    with patch("src.alert_manager.requests.post", return_value=_mock_post_ok()) as mp:
        result = alert.send_raw("Custom message")
        assert result is True
        assert mp.call_args.kwargs["json"]["text"] == "Custom message"
