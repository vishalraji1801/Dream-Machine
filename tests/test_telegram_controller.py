import threading
from unittest.mock import MagicMock, patch, call

import pytest

from src.telegram_controller import TelegramController


@pytest.fixture
def stop_event():
    return threading.Event()


@pytest.fixture
def status_fn():
    return MagicMock(return_value="Bot running. 2 positions open.")


@pytest.fixture
def ctrl(stop_event, status_fn):
    return TelegramController(
        bot_token="dummy_token",
        chat_id="123456",
        stop_event=stop_event,
        status_fn=status_fn,
    )


def _updates(*texts, chat_id="123456", start_id=1):
    return {
        "result": [
            {
                "update_id": start_id + i,
                "message": {
                    "chat": {"id": int(chat_id)},
                    "text": t,
                },
            }
            for i, t in enumerate(texts)
        ]
    }


# ── poll_once ─────────────────────────────────────────────────────────────────

def test_stop_command_sets_stop_event(ctrl, stop_event):
    response = MagicMock()
    response.json.return_value = _updates("/stop")
    response.raise_for_status = MagicMock()
    with patch("src.telegram_controller.requests.get", return_value=response), \
         patch("src.telegram_controller.requests.post"):
        ctrl._poll_once()
    assert stop_event.is_set()


def test_status_command_calls_status_fn(ctrl, stop_event, status_fn):
    response = MagicMock()
    response.json.return_value = _updates("/status")
    response.raise_for_status = MagicMock()
    with patch("src.telegram_controller.requests.get", return_value=response), \
         patch("src.telegram_controller.requests.post") as mock_post:
        ctrl._poll_once()
    status_fn.assert_called_once()
    sent_text = mock_post.call_args.kwargs["json"]["text"]
    assert "Bot running" in sent_text


def test_unknown_command_sends_help_reply(ctrl):
    response = MagicMock()
    response.json.return_value = _updates("/foo")
    response.raise_for_status = MagicMock()
    with patch("src.telegram_controller.requests.get", return_value=response), \
         patch("src.telegram_controller.requests.post") as mock_post:
        ctrl._poll_once()
    sent_text = mock_post.call_args.kwargs["json"]["text"]
    assert "/stop" in sent_text


def test_ignores_message_from_wrong_chat_id(ctrl, stop_event):
    response = MagicMock()
    response.json.return_value = _updates("/stop", chat_id="999999")
    response.raise_for_status = MagicMock()
    with patch("src.telegram_controller.requests.get", return_value=response), \
         patch("src.telegram_controller.requests.post"):
        ctrl._poll_once()
    assert not stop_event.is_set()


def test_offset_advances_after_each_update(ctrl):
    response = MagicMock()
    response.json.return_value = _updates("/status", "/status", start_id=10)
    response.raise_for_status = MagicMock()
    with patch("src.telegram_controller.requests.get", return_value=response), \
         patch("src.telegram_controller.requests.post"):
        ctrl._poll_once()
    assert ctrl._offset == 12  # last update_id (11) + 1


def test_empty_updates_does_not_change_offset(ctrl):
    response = MagicMock()
    response.json.return_value = {"result": []}
    response.raise_for_status = MagicMock()
    with patch("src.telegram_controller.requests.get", return_value=response):
        ctrl._poll_once()
    assert ctrl._offset == 0


def test_poll_once_raises_on_http_error(ctrl):
    import requests as req
    response = MagicMock()
    response.raise_for_status.side_effect = req.exceptions.HTTPError("500")
    with patch("src.telegram_controller.requests.get", return_value=response):
        with pytest.raises(req.exceptions.HTTPError):
            ctrl._poll_once()


# ── start / stop thread ───────────────────────────────────────────────────────

def test_start_launches_daemon_thread(ctrl):
    response = MagicMock()
    response.json.return_value = {"result": []}
    response.raise_for_status = MagicMock()
    with patch("src.telegram_controller.requests.get", return_value=response), \
         patch("src.telegram_controller.time.sleep"):
        ctrl.start()
        assert ctrl._thread is not None
        assert ctrl._thread.is_alive()
        ctrl._stop_event.set()
        ctrl.stop()


def test_stop_event_exits_poll_loop(stop_event):
    ctrl = TelegramController("tok", "123", stop_event)
    stop_event.set()
    response = MagicMock()
    response.json.return_value = {"result": []}
    response.raise_for_status = MagicMock()
    with patch("src.telegram_controller.requests.get", return_value=response):
        ctrl._poll_loop()  # should return immediately without polling


def test_poll_error_does_not_crash_loop(ctrl, stop_event):
    call_count = {"n": 0}

    def flaky_get(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise Exception("network blip")
        stop_event.set()
        m = MagicMock()
        m.json.return_value = {"result": []}
        m.raise_for_status = MagicMock()
        return m

    with patch("src.telegram_controller.requests.get", side_effect=flaky_get), \
         patch("src.telegram_controller.time.sleep"):
        ctrl._poll_loop()

    assert call_count["n"] == 2


# ── status_fn not provided ────────────────────────────────────────────────────

def test_status_fn_none_sends_unavailable(stop_event):
    ctrl = TelegramController("tok", "123456", stop_event, status_fn=None)
    response = MagicMock()
    response.json.return_value = _updates("/status")
    response.raise_for_status = MagicMock()
    with patch("src.telegram_controller.requests.get", return_value=response), \
         patch("src.telegram_controller.requests.post") as mock_post:
        ctrl._poll_once()
    assert "unavailable" in mock_post.call_args.kwargs["json"]["text"].lower()


# ── reply failure does not raise ──────────────────────────────────────────────

def test_reply_failure_does_not_crash(ctrl):
    import requests as req
    response = MagicMock()
    response.json.return_value = _updates("/status")
    response.raise_for_status = MagicMock()
    with patch("src.telegram_controller.requests.get", return_value=response), \
         patch("src.telegram_controller.requests.post",
               side_effect=req.exceptions.ConnectionError("timeout")):
        ctrl._poll_once()  # should not raise
