"""Phase 5 API — backtest endpoints and strategy manager."""
import os
import shutil

import pytest
from fastapi.testclient import TestClient

from webapp.server import create_app
from webapp.settings import Settings

TOKEN = "p5-token"
AUTH = {"X-API-Token": TOKEN}
REAL_CONFIG = os.path.join("config", "config.yaml")


# ── backtest endpoints (faked job engine) ─────────────────────────────────────

class FakeJobs:
    def data_summary(self):
        return {"timeframes": {"15min": {"symbols": 2, "sample": ["ACME", "BETA"]}}}

    def submit(self, strategy, timeframe, window, overrides, symbols):
        if timeframe == "bad":
            raise ValueError("no stored candles for timeframe 'bad'")
        return "job123"

    def get(self, job_id):
        if job_id != "job123":
            return None
        return {"status": "done", "result": {"aggregate": {"total_trades": 0}}}


@pytest.fixture
def bt_client(monkeypatch):
    monkeypatch.setenv("WEBAPP_TOKEN", TOKEN)
    monkeypatch.setattr("webapp.routers.backtest.get_jobs", lambda _p: FakeJobs())
    return TestClient(create_app())


def test_backtest_requires_token(bt_client):
    assert bt_client.get("/api/backtest/data").status_code == 401


def test_backtest_data(bt_client):
    body = bt_client.get("/api/backtest/data", headers=AUTH).json()
    assert "15min" in body["timeframes"]


def test_backtest_submit_and_poll(bt_client):
    r = bt_client.post("/api/backtest", headers=AUTH,
                       json={"strategy": "", "timeframe": "15min", "window": 60})
    jid = r.json()["job_id"]
    assert jid == "job123"
    poll = bt_client.get(f"/api/backtest/{jid}", headers=AUTH).json()
    assert poll["status"] == "done"


def test_backtest_bad_timeframe_422(bt_client):
    r = bt_client.post("/api/backtest", headers=AUTH,
                       json={"strategy": "", "timeframe": "bad"})
    assert r.status_code == 422


def test_backtest_unknown_job_404(bt_client):
    assert bt_client.get("/api/backtest/nope", headers=AUTH).status_code == 404


# ── strategy manager (temp config copy) ───────────────────────────────────────

@pytest.fixture
def sm_client(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    shutil.copy(REAL_CONFIG, cfg)
    monkeypatch.setenv("WEBAPP_TOKEN", TOKEN)
    monkeypatch.setattr("webapp.routers.strategies.get_settings",
                        lambda: Settings(token=TOKEN, config_path=str(cfg)))
    monkeypatch.setattr("webapp.routers.strategies.STRATEGY_REGISTRY", {"demo": lambda *a: None})
    return TestClient(create_app())


def test_strategies_list(sm_client):
    body = sm_client.get("/api/strategies", headers=AUTH).json()
    assert body["registered"] == ["demo"]
    assert "active" in body


def test_set_active_registered(sm_client):
    r = sm_client.put("/api/strategies/active", headers=AUTH, json={"name": "demo"})
    assert r.status_code == 200 and r.json()["active"] == "demo"


def test_set_active_empty_ok(sm_client):
    r = sm_client.put("/api/strategies/active", headers=AUTH, json={"name": ""})
    assert r.status_code == 200 and r.json()["active"] == ""


def test_set_active_unregistered_422(sm_client):
    r = sm_client.put("/api/strategies/active", headers=AUTH, json={"name": "ghost"})
    assert r.status_code == 422
