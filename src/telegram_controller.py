"""
Telegram command controller.
Background thread polls getUpdates and handles /stop and /status commands.
Only responds to messages from the authorised TELEGRAM_CHAT_ID.
"""
import threading
import time
from typing import Callable, Optional

import requests

from src.logger import get_logger

logger = get_logger("telegram_controller")


class TelegramController:
    """
    Polls Telegram for incoming commands.
    /stop   — sets stop_event, triggering graceful bot shutdown
    /status — calls status_fn() and replies with current bot state
    """

    POLL_INTERVAL = 5  # seconds between polls

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        stop_event: threading.Event,
        status_fn: Optional[Callable[[], str]] = None,
    ):
        self._base = f"https://api.telegram.org/bot{bot_token}"
        self._chat_id = str(chat_id)
        self._stop_event = stop_event
        self._status_fn = status_fn
        self._offset = 0
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="telegram-ctrl"
        )
        self._thread.start()
        logger.info("Telegram controller started — listening for /stop and /status")

    def stop(self) -> None:
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._poll_once()
            except Exception as exc:
                logger.warning(f"Telegram poll error: {exc}")
            time.sleep(self.POLL_INTERVAL)

    def _poll_once(self) -> None:
        resp = requests.get(
            f"{self._base}/getUpdates",
            params={
                "offset": self._offset,
                "timeout": 4,
                "allowed_updates": ["message"],
            },
            timeout=10,
        )
        resp.raise_for_status()
        for update in resp.json().get("result", []):
            self._offset = update["update_id"] + 1
            self._handle(update)

    def _handle(self, update: dict) -> None:
        msg = update.get("message", {})
        chat_id = str(msg.get("chat", {}).get("id", ""))
        text = msg.get("text", "").strip().lower()

        if chat_id != self._chat_id:
            logger.debug(f"Ignoring message from unknown chat_id: {chat_id}")
            return

        if text == "/stop":
            logger.warning("Received /stop from Telegram — initiating graceful shutdown")
            self._reply("Shutdown requested. Squaring off all positions and stopping...")
            self._stop_event.set()

        elif text == "/status":
            status = self._status_fn() if self._status_fn else "Status unavailable."
            self._reply(status)

        else:
            self._reply(f"Unknown command: {text}\nAvailable: /stop, /status")

    def _reply(self, text: str) -> None:
        try:
            requests.post(
                f"{self._base}/sendMessage",
                json={"chat_id": self._chat_id, "text": text},
                timeout=10,
            )
        except Exception as exc:
            logger.warning(f"Telegram reply failed: {exc}")
