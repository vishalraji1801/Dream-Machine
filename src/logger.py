"""
Centralised logging setup.
Call setup_logging() once at startup; use get_logger(name) in every module.

Emits two log streams:
- Human-readable  : logs/trading_bot_YYYY-MM-DD.log
- Structured JSONL: logs/structured_YYYY-MM-DD.jsonl  (one JSON object per line,
  easy for the scheduled Claude agents to parse reliably).
"""
import json
import logging
import os
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler

_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
_initialized = False


class _BotFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        return f"[{ts}] [{record.levelname}] [{record.name}] — {record.getMessage()}"


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created).isoformat(timespec="seconds"),
            "level": record.levelname,
            "module": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str = "INFO", retention_days: int = 30) -> None:
    """Configure root logger with daily rotating file + console + JSONL handlers."""
    global _initialized
    if _initialized:
        return

    os.makedirs(_LOG_DIR, exist_ok=True)
    day = datetime.now().strftime('%Y-%m-%d')
    log_path = os.path.join(_LOG_DIR, f"trading_bot_{day}.log")
    json_path = os.path.join(_LOG_DIR, f"structured_{day}.jsonl")

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    fh = TimedRotatingFileHandler(
        log_path, when="midnight", interval=1,
        backupCount=retention_days, encoding="utf-8"
    )
    fh.setFormatter(_BotFormatter())
    root.addHandler(fh)

    jh = TimedRotatingFileHandler(
        json_path, when="midnight", interval=1,
        backupCount=retention_days, encoding="utf-8"
    )
    jh.setFormatter(_JsonFormatter())
    root.addHandler(jh)

    ch = logging.StreamHandler()
    ch.setFormatter(_BotFormatter())
    root.addHandler(ch)

    _initialized = True


def get_logger(name: str) -> logging.Logger:
    """Return a named logger. Calls setup_logging() with defaults if not yet initialized."""
    if not _initialized:
        setup_logging()
    return logging.getLogger(name)
