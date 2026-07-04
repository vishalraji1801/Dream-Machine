import logging
import pytest
import src.logger as log_mod
from src.logger import get_logger, setup_logging


@pytest.fixture(autouse=True)
def reset_logger():
    log_mod._initialized = False
    root = logging.getLogger()
    for h in root.handlers[:]:
        root.removeHandler(h)
    yield
    log_mod._initialized = False
    for h in logging.getLogger().handlers[:]:
        logging.getLogger().removeHandler(h)


def test_get_logger_returns_logger():
    logger = get_logger("test_module")
    assert isinstance(logger, logging.Logger)
    assert logger.name == "test_module"


def test_setup_logging_adds_handlers():
    setup_logging()
    assert len(logging.getLogger().handlers) >= 1


def test_setup_logging_idempotent():
    setup_logging()
    handler_count = len(logging.getLogger().handlers)
    setup_logging()
    assert len(logging.getLogger().handlers) == handler_count


def test_log_file_created(tmp_path, monkeypatch):
    monkeypatch.setattr(log_mod, "_LOG_DIR", str(tmp_path))
    setup_logging(level="DEBUG", retention_days=5)
    logger = get_logger("file_test")
    logger.info("test message written to file")
    log_files = list(tmp_path.glob("trading_bot_*.log"))
    assert len(log_files) == 1
    content = log_files[0].read_text(encoding="utf-8")
    assert "test message written to file" in content


def test_log_format_contains_required_fields(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(log_mod, "_LOG_DIR", str(tmp_path))
    setup_logging()
    logger = get_logger("format_check")
    logger.info("hello world")
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "[INFO]" in output
    assert "[format_check]" in output
    assert "hello world" in output


def test_log_levels_respected(tmp_path, monkeypatch):
    monkeypatch.setattr(log_mod, "_LOG_DIR", str(tmp_path))
    setup_logging(level="WARNING")
    log_files = list(tmp_path.glob("trading_bot_*.log"))
    assert len(log_files) == 1
