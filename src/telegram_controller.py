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
    /pause  — sets pause_event: no new entries, open positions still managed
    /resume — clears pause_event
    /status — calls status_fn() and replies with current bot state
    """

    POLL_INTERVAL = 5  # seconds between polls

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        stop_event: threading.Event,
        status_fn: Optional[Callable[[], str]] = None,
        pause_event: Optional[threading.Event] = None,
    ):
        self._base = f"https://api.telegram.org/bot{bot_token}"
        self._chat_id = str(chat_id)
        self._stop_event = stop_event
        self._pause_event = pause_event
        self._status_fn = status_fn
        self._offset = 0
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._flush_backlog()
        self._thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="telegram-ctrl"
        )
        self._thread.start()
        logger.info("Telegram controller started — listening for /stop and /status")

    def _flush_backlog(self) -> None:
        """Discard commands sent while the bot was offline (Telegram retains
        updates ~24h; a /stop from yesterday must not kill today's session)."""
        try:
            resp = requests.get(
                f"{self._base}/getUpdates",
                params={"offset": -1, "timeout": 0}, timeout=10,
            )
            resp.raise_for_status()
            results = resp.json().get("result", [])
            if results:
                self._offset = results[-1]["update_id"] + 1
                # acknowledge server-side so the stale updates are dropped for good
                requests.get(
                    f"{self._base}/getUpdates",
                    params={"offset": self._offset, "timeout": 0}, timeout=10,
                )
                logger.warning("Flushed stale Telegram command(s) from before startup")
        except Exception as exc:
            logger.warning(f"Telegram backlog flush failed (continuing): {exc}")

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

        elif text == "/pause":
            if self._pause_event is None:
                self._reply("Pause is not supported in this session.")
            else:
                self._pause_event.set()
                logger.warning("Received /pause — new entries suspended")
                self._reply("Paused. No new entries; open positions still managed. /resume to continue.")

        elif text == "/resume":
            if self._pause_event is None:
                self._reply("Pause is not supported in this session.")
            else:
                self._pause_event.clear()
                logger.warning("Received /resume — entries re-enabled")
                self._reply("Resumed. New entries re-enabled.")

        elif text == "/status":
            status = self._status_fn() if self._status_fn else "Status unavailable."
            self._reply(status)

        else:
            self._reply(f"Unknown command: {text}\nAvailable: /stop, /pause, /resume, /status")

    def _reply(self, text: str) -> None:
        try:
            requests.post(
                f"{self._base}/sendMessage",
                json={"chat_id": self._chat_id, "text": text},
                timeout=10,
            )
        except Exception as exc:
            logger.warning(f"Telegram reply failed: {exc}")
