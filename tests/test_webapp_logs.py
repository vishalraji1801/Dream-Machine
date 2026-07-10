"""Phase 6 — log viewer: listing, tailing, and path-traversal safety."""
import pytest
from fastapi.testclient import TestClient

from webapp.logs_reader import list_logs, tail_log
from webapp.server import create_app
from webapp.settings import Settings

TOKEN = "logs-token"
AUTH = {"X-API-Token": TOKEN}


@pytest.fixture
def log_dir(tmp_path):
    (tmp_path / "trading_bot_2026-07-10.log").write_text(
        "\n".join(f"line {i}" for i in range(500)), encoding="utf-8")
    (tmp_path / "old.log").write_text("just one line", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("SHOULD NOT BE READABLE", encoding="utf-8")
    (tmp_path / "trades.db").write_text("binary-ish", encoding="utf-8")
    return str(tmp_path)


# ── unit ──────────────────────────────────────────────────────────────────────

def test_list_only_log_files(log_dir):
    names = {f["name"] for f in list_logs(log_dir)}
    assert names == {"trading_bot_2026-07-10.log", "old.log"}


def test_tail_returns_last_n(log_dir):
    res = tail_log(log_dir, "trading_bot_2026-07-10.log", lines=10)
    assert res["lines"][-1] == "line 499"
    assert len(res["lines"]) == 10


def test_tail_rejects_non_log(log_dir):
    assert tail_log(log_dir, "secret.txt", 10) is None
    assert tail_log(log_dir, "trades.db", 10) is None


def test_tail_rejects_traversal(log_dir):
    assert tail_log(log_dir, "../config/config.yaml", 10) is None
    assert tail_log(log_dir, "..\\..\\.env", 10) is None
    assert tail_log(log_dir, "sub/evil.log", 10) is None


# ── API ───────────────────────────────────────────────────────────────────────

@pytest.fixture
def client(log_dir, monkeypatch):
    monkeypatch.setenv("WEBAPP_TOKEN", TOKEN)
    monkeypatch.setattr("webapp.routers.logs.get_settings",
                        lambda: Settings(token=TOKEN, log_dir=log_dir))
    return TestClient(create_app())


def test_logs_requires_token(client):
    assert client.get("/api/logs").status_code == 401


def test_logs_list(client):
    body = client.get("/api/logs", headers=AUTH).json()
    assert len(body["files"]) == 2


def test_logs_tail(client):
    body = client.get("/api/logs/trading_bot_2026-07-10.log?lines=5", headers=AUTH).json()
    assert len(body["lines"]) == 5


def test_logs_tail_404_on_bad(client):
    assert client.get("/api/logs/secret.txt", headers=AUTH).status_code == 404
