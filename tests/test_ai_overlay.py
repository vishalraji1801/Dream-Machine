import yaml

from src.ai_overlay import apply_overlay, load_overlay


def _cfg(tmp_path, overlay_body=None, enabled=True):
    path = tmp_path / "ai_overlay.yaml"
    if overlay_body is not None:
        path.write_text(yaml.safe_dump(overlay_body))
    cfg = {
        "trading": {"market_open": "09:15", "market_close": "15:30",
                    "entry_start_time": "09:45", "entry_end_time": "14:30"},
        "strategy": {"name": "momentum_vwap_breakout", "rsi_entry_threshold": 60,
                     "volume_multiplier": 1.5},
        "risk": {"stop_loss_pct": 1.0, "target_pct": 2.0, "max_trades_per_day": 8},
        "ai": {
            "overlay_enabled": enabled,
            "overlay_path": str(path),
            "allowed_strategies": ["momentum_vwap_breakout", "vwap_mean_reversion", "orb"],
            "min_stop_loss_pct": 0.5, "max_stop_loss_pct": 2.0,
            "min_target_pct": 0.5, "max_target_pct": 5.0,
        },
    }
    return cfg


# ── valid overlays ────────────────────────────────────────────────────────────

def test_valid_overlay_loads(tmp_path):
    cfg = _cfg(tmp_path, {"strategy": {"rsi_entry_threshold": 65},
                          "risk": {"stop_loss_pct": 1.5}})
    overlay, err = load_overlay(cfg)
    assert err is None
    assert overlay == {"strategy": {"rsi_entry_threshold": 65},
                       "risk": {"stop_loss_pct": 1.5}}


def test_meta_block_is_ignored(tmp_path):
    cfg = _cfg(tmp_path, {"meta": {"note": "hi"}, "strategy": {"volume_multiplier": 2.0}})
    overlay, err = load_overlay(cfg)
    assert err is None
    assert overlay == {"strategy": {"volume_multiplier": 2.0}}


def test_meta_only_is_noop(tmp_path):
    cfg = _cfg(tmp_path, {"meta": {"note": "no change"}})
    overlay, err = load_overlay(cfg)
    assert err is None
    assert overlay == {}


def test_apply_overlay_merges_without_mutating(tmp_path):
    cfg = _cfg(tmp_path)
    overlay = {"strategy": {"rsi_entry_threshold": 70}, "risk": {"target_pct": 3.0}}
    merged = apply_overlay(cfg, overlay)
    assert merged["strategy"]["rsi_entry_threshold"] == 70
    assert merged["risk"]["target_pct"] == 3.0
    # original untouched
    assert cfg["strategy"]["rsi_entry_threshold"] == 60
    assert cfg["risk"]["target_pct"] == 2.0
    # untouched fields preserved
    assert merged["strategy"]["volume_multiplier"] == 1.5


# ── missing / disabled ────────────────────────────────────────────────────────

def test_missing_file_is_noop(tmp_path):
    cfg = _cfg(tmp_path)  # no file written
    assert load_overlay(cfg) == (None, None)


def test_disabled_returns_noop(tmp_path):
    cfg = _cfg(tmp_path, {"strategy": {"rsi_entry_threshold": 65}}, enabled=False)
    assert load_overlay(cfg) == (None, None)


# ── rejections ────────────────────────────────────────────────────────────────

def test_reject_unknown_section(tmp_path):
    cfg = _cfg(tmp_path, {"costs": {"enabled": False}})
    overlay, err = load_overlay(cfg)
    assert overlay is None
    assert "not adjustable" in err


def test_reject_immutable_field(tmp_path):
    cfg = _cfg(tmp_path, {"risk": {"total_capital": 999}})
    overlay, err = load_overlay(cfg)
    assert overlay is None
    assert "total_capital" in err


def test_reject_stop_loss_out_of_bounds(tmp_path):
    cfg = _cfg(tmp_path, {"risk": {"stop_loss_pct": 5.0}})
    overlay, err = load_overlay(cfg)
    assert overlay is None
    assert "stop_loss_pct" in err


def test_reject_unknown_strategy_name(tmp_path):
    cfg = _cfg(tmp_path, {"strategy": {"name": "wild_martingale"}})
    overlay, err = load_overlay(cfg)
    assert overlay is None
    assert "allowed_strategies" in err


def test_reject_rsi_out_of_bounds(tmp_path):
    cfg = _cfg(tmp_path, {"strategy": {"rsi_entry_threshold": 95}})
    overlay, err = load_overlay(cfg)
    assert overlay is None
    assert "rsi_entry_threshold" in err


def test_reject_entry_time_outside_hours(tmp_path):
    cfg = _cfg(tmp_path, {"trading": {"entry_start_time": "08:00"}})
    overlay, err = load_overlay(cfg)
    assert overlay is None
    assert "outside market hours" in err


def test_reject_max_trades_out_of_bounds(tmp_path):
    cfg = _cfg(tmp_path, {"risk": {"max_trades_per_day": 99}})
    overlay, err = load_overlay(cfg)
    assert overlay is None
    assert "max_trades_per_day" in err


def test_reject_unparseable_yaml(tmp_path):
    path = tmp_path / "ai_overlay.yaml"
    path.write_text("{not: valid: yaml: here")
    cfg = _cfg(tmp_path)
    overlay, err = load_overlay(cfg)
    assert overlay is None
    assert "unreadable" in err


def test_reject_non_mapping(tmp_path):
    path = tmp_path / "ai_overlay.yaml"
    path.write_text("- just\n- a\n- list\n")
    cfg = _cfg(tmp_path)
    overlay, err = load_overlay(cfg)
    assert overlay is None
    assert "not a mapping" in err
