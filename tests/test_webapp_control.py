"""Phase 2 — control endpoints and the live WebSocket (supervisor faked)."""
import pytest
from fastapi.testclient import TestClient

from webapp.server import create_app

TOKEN = "ctl-test-token"
AUTH = {"X-API-Token": TOKEN}


class FakeSupervisor:
    def __init__(self):
        self.calls = []
        self.running = False

    def state(self):
        return {"running": self.running, "pid": 1234 if self.running else None,
                "mode": "paper"}

    def start(self):
        self.calls.append("start"); self.running = True
        return {"started": True, "pid": 1234}

    def stop(self):
        self.calls.append("stop"); self.running = False
        return {"stopped": True, "graceful": True}

    def pause(self):
        self.calls.append("pause"); return {"ok": True, "command": "pause"}

    def resume(self):
        self.calls.append("resume"); return {"ok": True, "command": "resume"}

    def square_off(self):
        self.calls.append("square_off"); return {"ok": True, "command": "square_off"}


@pytest.fixture
def fake(monkeypatch):
    sup = FakeSupervisor()
    monkeypatch.setattr("webapp.routers.control.get_supervisor", lambda: sup)
    monkeypatch.setattr("webapp.ws.get_supervisor", lambda: sup)
    return sup


@pytest.fixture
def client(monkeypatch, fake):
    monkeypatch.setenv("WEBAPP_TOKEN", TOKEN)
    return TestClient(create_app())


# ── auth still applies ────────────────────────────────────────────────────────

def test_control_requires_token(client):
    assert client.post("/api/control/start").status_code == 401


# ── lifecycle ─────────────────────────────────────────────────────────────────

def test_state_reports_stopped(client, fake):
    body = client.get("/api/control/state", headers=AUTH).json()
    assert body["running"] is False and body["mode"] == "paper"


def test_start_stop_pause_resume_squareoff(client, fake):
    assert client.post("/api/control/start", headers=AUTH).json()["started"] is True
    assert client.post("/api/control/pause", headers=AUTH).json()["ok"] is True
    assert client.post("/api/control/resume", headers=AUTH).json()["ok"] is True
    assert client.post("/api/control/squareoff", headers=AUTH).json()["ok"] is True
    assert client.post("/api/control/stop", headers=AUTH).json()["stopped"] is True
    assert fake.calls == ["start", "pause", "resume", "square_off", "stop"]


# ── live-mode guard ───────────────────────────────────────────────────────────

def test_live_start_blocked_without_confirm(client, fake, monkeypatch):
    monkeypatch.setattr("webapp.routers.control.get_trading_mode", lambda: "live")
    r = client.post("/api/control/start", headers=AUTH, json={"confirm_live": False})
    assert r.status_code == 409
    assert "start" not in fake.calls


def test_live_start_allowed_with_confirm(client, fake, monkeypatch):
    monkeypatch.setattr("webapp.routers.control.get_trading_mode", lambda: "live")
    r = client.post("/api/control/start", headers=AUTH, json={"confirm_live": True})
    assert r.status_code == 200
    assert "start" in fake.calls


# ── live websocket ────────────────────────────────────────────────────────────

def test_ws_pushes_snapshot_with_valid_token(client, fake):
    with client.websocket_connect(f"/ws/live?token={TOKEN}") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "snapshot"
        assert "positions" in msg and "daily_pnl" in msg


def test_ws_rejects_bad_token(client, fake):
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/live?token=wrong") as ws:
            ws.receive_json()
