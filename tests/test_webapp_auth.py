"""TOTP login -> session flow (Kite call mocked; no network)."""
import pytest
from fastapi.testclient import TestClient

import webapp.routers.auth_login as auth_login
from auth import AuthError
from webapp.server import create_app
from webapp.sessions import get_sessions


@pytest.fixture(autouse=True)
def reset_throttle():
    auth_login._attempts.clear()
    yield
    auth_login._attempts.clear()


@pytest.fixture
def client(monkeypatch):
    # no static token — force the session path
    monkeypatch.delenv("WEBAPP_TOKEN", raising=False)
    monkeypatch.setattr("webapp.settings._TOKEN_FILE", "does-not-exist.txt")
    return TestClient(create_app())


def _mock_ok(monkeypatch):
    monkeypatch.setattr(auth_login, "authenticate_with_totp",
                        lambda totp: {"access_token": "tok", "user_id": "AB1234"})


def _mock_fail(monkeypatch, msg="2FA rejected by Kite"):
    def boom(totp):
        raise AuthError(msg)
    monkeypatch.setattr(auth_login, "authenticate_with_totp", boom)


# ── login ─────────────────────────────────────────────────────────────────────

def test_login_success_issues_session(client, monkeypatch):
    _mock_ok(monkeypatch)
    r = client.post("/api/auth/login", json={"totp": "123456"})
    assert r.status_code == 200
    token = r.json()["token"]
    assert get_sessions().validate(token)
    # and that session now authorizes protected endpoints
    assert client.get("/api/status", headers={"X-API-Token": token}).status_code == 200


def test_login_bad_totp_401(client, monkeypatch):
    _mock_fail(monkeypatch)
    r = client.post("/api/auth/login", json={"totp": "000000"})
    assert r.status_code == 401
    assert "2FA" in r.json()["detail"]


def test_protected_blocked_before_login(client):
    assert client.get("/api/status").status_code == 401


def test_login_is_throttled(client, monkeypatch):
    _mock_fail(monkeypatch)
    codes = [client.post("/api/auth/login", json={"totp": "x"}).status_code for _ in range(7)]
    assert codes[:5] == [401] * 5      # first 5 attempts hit the auth path
    assert 429 in codes[5:]            # then throttled


def test_logout_revokes_session(client, monkeypatch):
    _mock_ok(monkeypatch)
    token = client.post("/api/auth/login", json={"totp": "123456"}).json()["token"]
    h = {"X-API-Token": token}
    assert client.get("/api/status", headers=h).status_code == 200
    client.post("/api/auth/logout", headers=h)
    assert client.get("/api/status", headers=h).status_code == 401


def test_ws_accepts_session_token(client, monkeypatch):
    _mock_ok(monkeypatch)
    token = client.post("/api/auth/login", json={"totp": "123456"}).json()["token"]
    with client.websocket_connect(f"/ws/live?token={token}") as ws:
        assert ws.receive_json()["type"] == "snapshot"
