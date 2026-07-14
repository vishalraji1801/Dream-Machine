"""
Command channel — out-of-process control for the trading loop.

The web API runs as a separate process (so the web stack never sits in the order
path). It cannot touch the bot's in-memory stop/pause events directly, and on
Windows terminating the subprocess is a hard kill that would skip the graceful
end-of-day square-off. So control flows through this file-backed queue instead:

    supervisor  ──send("stop")──▶  logs/commands.jsonl  ──poll()──▶  bot loop

An append-only JSONL log + a byte-offset marker gives an ordered, lossless queue
(no command overwrites another) that survives restarts. The bot seeks to the end
at startup so stale commands from a previous run are ignored — the same reason
the Telegram controller flushes its backlog.
"""
import json
import os
import threading
from datetime import datetime
from typing import Optional

from src.logger import get_logger

logger = get_logger("command_channel")

VALID_COMMANDS = ("stop", "pause", "resume", "square_off")


class CommandChannel:
    def __init__(self, path: str = os.path.join("logs", "commands.jsonl"),
                 offset_path: Optional[str] = None):
        self._path = path
        self._offset_path = offset_path or (path + ".offset")
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    # ── supervisor side ─────────────────────────────────────────────────────────

    def send(self, cmd: str, **payload) -> dict:
        """Append a command. Raises ValueError for an unknown command."""
        if cmd not in VALID_COMMANDS:
            raise ValueError(f"unknown command: {cmd!r} (valid: {VALID_COMMANDS})")
        entry = {"cmd": cmd, "ts": datetime.now().isoformat(timespec="seconds"), **payload}
        with self._lock:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        logger.info(f"queued command: {cmd}")
        return entry

    # ── bot side ────────────────────────────────────────────────────────────────

    def seek_to_end(self) -> None:
        """Mark all existing commands as consumed (call at bot startup so stale
        commands from a previous run are not replayed)."""
        size = os.path.getsize(self._path) if os.path.exists(self._path) else 0
        self._write_offset(size)

    def poll(self) -> list[dict]:
        """Return commands appended since the last poll, advancing the marker.
        Malformed lines are skipped. Safe to call when the file doesn't exist."""
        if not os.path.exists(self._path):
            return []
        offset = self._read_offset()
        out: list[dict] = []
        with self._lock, open(self._path, "r", encoding="utf-8") as f:
            f.seek(offset)
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning(f"skipping malformed command line: {line!r}")
            new_offset = f.tell()
        self._write_offset(new_offset)
        return out

    # ── offset persistence ──────────────────────────────────────────────────────

    def _read_offset(self) -> int:
        try:
            with open(self._offset_path, encoding="utf-8") as f:
                return int(f.read().strip() or 0)
        except (OSError, ValueError):
            return 0

    def _write_offset(self, value: int) -> None:
        try:
            with open(self._offset_path, "w", encoding="utf-8") as f:
                f.write(str(value))
        except OSError as exc:
            logger.error(f"failed to persist command offset: {exc}")
