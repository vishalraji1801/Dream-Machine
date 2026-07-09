"""Phase 1 web backend — auth boundary and read-endpoint contracts."""
import pytest
from fastapi.testclient import TestClient

from webapp.server import create_app

TOKEN = "unit-test-token"
AUTH = {"X-API-Token": TOKEN}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("WEBAPP_TOKEN", TOKEN)
    return TestClient(create_app())


@pytest.fixture
def no_token_client(monkeypatch):
    monkeypatch.delenv("WEBAPP_TOKEN", raising=False)
    return TestClient(create_app())


# ── auth boundary ─────────────────────────────────────────────────────────────

def test_health_is_open(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["token_configured"] is True


def test_protected_rejects_missing_token(client):
    assert client.get("/api/status").status_code == 401


def test_protected_rejects_bad_token(client):
    assert client.get("/api/status", headers={"X-API-Token": "nope"}).status_code == 401


def test_protected_accepts_bearer(client):
    r = client.get("/api/status", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200


def test_protected_accepts_header_token(client):
    assert client.get("/api/status", headers=AUTH).status_code == 200


def test_503_when_no_token_configured(no_token_client, tmp_path, monkeypatch):
    # point the token file away so none is found
    monkeypatch.setattr("webapp.settings._TOKEN_FILE", str(tmp_path / "absent.txt"))
    assert no_token_client.get("/api/status").status_code == 503


# ── read contracts ────────────────────────────────────────────────────────────

def test_status_shape(client):
    body = client.get("/api/status", headers=AUTH).json()
    assert body["mode"] in ("paper", "live")
    assert "gate_ready" in body


def test_positions_shape(client):
    body = client.get("/api/positions", headers=AUTH).json()
    assert set(body) >= {"positions", "daily_pnl", "trades_today", "stale"}
    assert isinstance(body["positions"], list)


def test_trades_shape(client):
    body = client.get("/api/trades", headers=AUTH).json()
    assert "count" in body and isinstance(body["trades"], list)
    assert body["count"] == len(body["trades"])


def test_trades_source_filter_validated(client):
    assert client.get("/api/trades?source=bogus", headers=AUTH).status_code == 422
    assert client.get("/api/trades?source=paper", headers=AUTH).status_code == 200


def test_signals_shape(client):
    body = client.get("/api/signals", headers=AUTH).json()
    assert "count" in body and isinstance(body["signals"], list)


def test_equity_shape(client):
    body = client.get("/api/equity", headers=AUTH).json()
    assert set(body) >= {"snapshots", "trade_curve", "net_pnl", "trade_count"}
    assert isinstance(body["trade_curve"], list)
