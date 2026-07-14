"""Phase 4 — config editor: bounds, coercion, comment-preserving writes, API."""
import os
import shutil

import pytest
from fastapi.testclient import TestClient

from webapp.config_editor import apply_updates, read_config, validate_updates
from webapp.server import create_app
from webapp.settings import Settings

REAL_CONFIG = os.path.join("config", "config.yaml")
TOKEN = "cfg-test-token"
AUTH = {"X-API-Token": TOKEN}


@pytest.fixture
def cfg_file(tmp_path):
    dst = tmp_path / "config.yaml"
    shutil.copy(REAL_CONFIG, dst)
    return str(dst)


# ── unit: read / validate / apply ─────────────────────────────────────────────

def test_read_returns_groups_and_values(cfg_file):
    data = read_config(cfg_file)
    sections = {g["section"] for g in data["groups"]}
    assert {"risk", "strategy", "trading", "scheduler"} <= sections
    risk = next(g for g in data["groups"] if g["section"] == "risk")
    cap = next(f for f in risk["fields"] if f["key"] == "total_capital")
    assert cap["value"] == 1_000_000 and cap["type"] == "number"


def test_validate_rejects_unknown_field():
    with pytest.raises(ValueError, match="not an editable field"):
        validate_updates({"risk": {"total_capital_evil": 5}})


def test_validate_rejects_out_of_bounds():
    with pytest.raises(ValueError, match="max is"):
        validate_updates({"risk": {"max_risk_per_trade_pct": 99}})
    with pytest.raises(ValueError, match="min is"):
        validate_updates({"risk": {"total_capital": 1}})


def test_validate_select_and_time():
    with pytest.raises(ValueError, match="one of"):
        validate_updates({"strategy": {"sl_mode": "bogus"}})
    with pytest.raises(ValueError, match="HH:MM"):
        validate_updates({"trading": {"entry_start_time": "9am"}})


def test_int_vs_float_coercion():
    clean = validate_updates({
        "risk": {"max_open_positions": 4.0, "max_risk_per_trade_pct": 1.5},
        "strategy": {"volume_multiplier": 1.8},
    })
    assert clean["risk"]["max_open_positions"] == 4
    assert isinstance(clean["risk"]["max_open_positions"], int)
    assert clean["strategy"]["volume_multiplier"] == 1.8


def test_apply_writes_and_preserves_comments(cfg_file):
    before = open(cfg_file, encoding="utf-8").read()
    assert "# Set to false to go live" in before  # a known comment
    apply_updates(cfg_file, {"risk": {"max_open_positions": 5, "stop_loss_pct": 1.5}})
    after = open(cfg_file, encoding="utf-8").read()
    assert "# Set to false to go live" in after   # comment survived
    data = read_config(cfg_file)
    risk = next(g for g in data["groups"] if g["section"] == "risk")
    assert next(f for f in risk["fields"] if f["key"] == "max_open_positions")["value"] == 5


def test_apply_nested_mtf_field(cfg_file):
    apply_updates(cfg_file, {"strategy": {"mtf_confirm.enabled": True,
                                          "mtf_confirm.higher_tf": "30min"}})
    data = read_config(cfg_file)
    strat = next(g for g in data["groups"] if g["section"] == "strategy")
    assert next(f for f in strat["fields"] if f["key"] == "mtf_confirm.enabled")["value"] is True
    assert next(f for f in strat["fields"] if f["key"] == "mtf_confirm.higher_tf")["value"] == "30min"


# ── API ───────────────────────────────────────────────────────────────────────

@pytest.fixture
def client(cfg_file, monkeypatch):
    monkeypatch.setenv("WEBAPP_TOKEN", TOKEN)
    monkeypatch.setattr("webapp.routers.config.get_settings",
                        lambda: Settings(token=TOKEN, config_path=cfg_file))
    return TestClient(create_app())


def test_get_config_requires_token(client):
    assert client.get("/api/config").status_code == 401


def test_get_config_ok(client):
    body = client.get("/api/config", headers=AUTH).json()
    assert any(g["section"] == "risk" for g in body["groups"])


def test_put_config_saves(client):
    r = client.put("/api/config", headers=AUTH,
                   json={"updates": {"risk": {"max_trades_per_day": 6}}})
    assert r.status_code == 200 and r.json()["saved"] is True


def test_put_config_rejects_bad_value(client):
    r = client.put("/api/config", headers=AUTH,
                   json={"updates": {"risk": {"stop_loss_pct": 999}}})
    assert r.status_code == 422
