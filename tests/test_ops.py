import pytest

from src.ops import (format_status, get_trading_mode, golive_decision,
                     set_trading_mode)

_CONFIG = """trading:
  exchange: NSE

paper_trading:
  enabled: true           # Set to false to go live with real orders
  simulated_slippage_pct: 0.05  # slippage on simulated fills
  realistic_fills: true

logging:
  level: INFO
"""


@pytest.fixture
def cfg_file(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(_CONFIG, encoding="utf-8")
    return str(p)


# ── mode switch ───────────────────────────────────────────────────────────────

def test_get_mode_paper(cfg_file):
    assert get_trading_mode(cfg_file) == "paper"


def test_flip_to_live_and_back(cfg_file):
    assert set_trading_mode(live=True, config_path=cfg_file) == "live"
    assert get_trading_mode(cfg_file) == "live"
    assert set_trading_mode(live=False, config_path=cfg_file) == "paper"
    assert get_trading_mode(cfg_file) == "paper"


def test_flip_preserves_comments_and_other_keys(cfg_file):
    set_trading_mode(live=True, config_path=cfg_file)
    text = open(cfg_file, encoding="utf-8").read()
    assert "# Set to false to go live with real orders" in text   # comment kept
    assert "simulated_slippage_pct: 0.05" in text                 # neighbors intact
    assert "realistic_fills: true" in text                        # not touched
    assert "enabled: false" in text


def test_flip_raises_when_key_missing(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("trading:\n  exchange: NSE\n", encoding="utf-8")
    with pytest.raises(ValueError):
        set_trading_mode(live=True, config_path=str(p))


# ── golive decision ───────────────────────────────────────────────────────────

def _paper_trades(n, pnl=150.0):
    return [{"pnl": pnl, "entry_time": f"2026-07-{(i % 6) + 1:02d} 10:00:00"}
            for i in range(n)]


def test_golive_allowed_when_gate_passes():
    d = golive_decision(_paper_trades(30))
    assert d["ready"] is True
    assert d["allowed"] is True
    assert d["forced"] is False


def test_golive_blocked_when_gate_fails():
    d = golive_decision(_paper_trades(3))     # too few trades/days
    assert d["ready"] is False
    assert d["allowed"] is False


def test_golive_force_overrides_but_is_flagged():
    d = golive_decision(_paper_trades(3), force=True)
    assert d["ready"] is False
    assert d["allowed"] is True
    assert d["forced"] is True


# ── status formatting ─────────────────────────────────────────────────────────

def test_format_status_paper():
    text = format_status({
        "mode": "paper", "market": "OPEN", "token_fresh_today": True,
        "token_time": "2026-07-06 09:00", "paper_trades": 12,
        "paper_net_pnl": 840.5, "gate_ready": False,
        "gate_checks": {"trade_count": False, "net_pnl": True},
        "latest_backtest": "logs/backtest_matrix_2026-07-05.md",
    })
    assert "mode: PAPER" in text
    assert "fresh (today)" in text
    assert "[FAIL] trade_count" in text and "[PASS] net_pnl" in text
    assert "REAL ORDERS" not in text


def test_format_status_live_warns():
    text = format_status({
        "mode": "live", "market": "OPEN", "token_fresh_today": False,
        "token_time": None, "paper_trades": 40, "paper_net_pnl": 5000.0,
        "gate_ready": True, "gate_checks": {}, "latest_backtest": None,
    })
    assert "mode: LIVE" in text
    assert "REAL ORDERS ARE ENABLED" in text
    assert "STALE" in text
