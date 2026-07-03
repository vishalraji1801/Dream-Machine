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
                            qty=5, price=2845.50, order_id="1234567890")
        assert result is True
        mp.assert_called_once()
        payload = mp.call_args.kwargs["json"]
        assert "BUY" in payload["text"]
        assert "RELIANCE" in payload["text"]


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
        "bot_started":     {"minutes": 10},
        "order_placed":    {"direction": "BUY", "symbol": "TCS", "qty": 2, "price": 3500.0, "order_id": "ABC"},
        "order_filled":    {"symbol": "TCS", "actual_price": 3502.0, "slippage": 2.0},
        "order_rejected":  {"symbol": "TCS", "reason": "Insufficient funds"},
        "sl_hit":          {"symbol": "TCS", "entry": 3500.0, "exit_price": 3465.0, "loss": 70.0},
        "target_hit":      {"symbol": "TCS", "entry": 3500.0, "exit_price": 3570.0, "profit": 140.0},
        "circuit_breaker": {"reason": "Daily loss limit"},
        "critical_error":  {"module": "strategy", "message": "Unexpected error"},
        "daily_summary":   {"trades": 3, "profit": 5000, "loss": 2000, "net_pnl": 3000},
    }
    with patch("src.alert_manager.requests.post", return_value=_mock_post_ok()):
        alert = AlertManager("tok", "cid")
        for event, kwargs in event_kwargs.items():
            assert alert.send(event, **kwargs) is True, f"Failed for event: {event}"


def test_all_templates_defined():
    expected = {
        "bot_started", "order_placed", "order_filled", "order_rejected",
        "sl_hit", "target_hit", "circuit_breaker", "critical_error", "daily_summary",
    }
    assert expected == set(_TEMPLATES.keys())


def test_send_raw(alert):
    with patch("src.alert_manager.requests.post", return_value=_mock_post_ok()) as mp:
        result = alert.send_raw("Custom message")
        assert result is True
        assert mp.call_args.kwargs["json"]["text"] == "Custom message"
