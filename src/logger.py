"""
Centralised logging setup.
Call setup_logging() once at startup; use get_logger(name) in every module.
"""
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


def setup_logging(level: str = "INFO", retention_days: int = 30) -> None:
    """Configure root logger with daily rotating file + console handlers."""
    global _initialized
    if _initialized:
        return

    os.makedirs(_LOG_DIR, exist_ok=True)
    log_path = os.path.join(_LOG_DIR, f"trading_bot_{datetime.now().strftime('%Y-%m-%d')}.log")
    formatter = _BotFormatter()

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    fh = TimedRotatingFileHandler(
        log_path, when="midnight", interval=1,
        backupCount=retention_days, encoding="utf-8"
    )
    fh.setFormatter(formatter)
    root.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setFormatter(formatter)
    root.addHandler(ch)

    _initialized = True


def get_logger(name: str) -> logging.Logger:
    """Return a named logger. Calls setup_logging() with defaults if not yet initialized."""
    if not _initialized:
        setup_logging()
    return logging.getLogger(name)
