from unittest.mock import MagicMock

import pytest

from src.param_sweep import expand_grid, format_sweep_report, run_sweep


# ── expand_grid ───────────────────────────────────────────────────────────────

def test_expand_grid_cartesian_product():
    grid = expand_grid({"a": [1, 2], "b": [10, 20, 30]})
    assert len(grid) == 6
    assert {"a": 1, "b": 10} in grid
    assert {"a": 2, "b": 30} in grid


def test_expand_grid_single_param():
    grid = expand_grid({"rsi_entry_threshold": [55, 60, 65]})
    assert grid == [{"rsi_entry_threshold": 55},
                    {"rsi_entry_threshold": 60},
                    {"rsi_entry_threshold": 65}]


def test_expand_grid_empty():
    assert expand_grid({}) == [{}]


# ── run_sweep ─────────────────────────────────────────────────────────────────

def _fake_backtester_cls(pnl_by_rsi):
    """Backtester replacement whose result depends on the injected cfg."""
    class Fake:
        def __init__(self, cfg, window=60):
            self._cfg = cfg

        def run(self, candles, index_candles=None):
            r = MagicMock()
            r.net_pnl = pnl_by_rsi[self._cfg["strategy"]["rsi_entry_threshold"]]
            r.win_rate = 50.0
            r.profit_factor = 1.5
            r.max_drawdown = 1000.0
            r.total_trades = 10
            return r
    return Fake


@pytest.fixture
def base_cfg():
    return {"strategy": {"rsi_entry_threshold": 60}, "risk": {}, "trading": {}}


def test_run_sweep_applies_params_and_sorts_by_pnl(base_cfg):
    grid = [{"rsi_entry_threshold": 55}, {"rsi_entry_threshold": 60},
            {"rsi_entry_threshold": 65}]
    fake = _fake_backtester_cls({55: 100.0, 60: 900.0, 65: 400.0})
    results = run_sweep(base_cfg, {}, grid, backtester_cls=fake)
    assert [r["net_pnl"] for r in results] == [900.0, 400.0, 100.0]
    assert results[0]["params"] == {"rsi_entry_threshold": 60}


def test_run_sweep_does_not_mutate_base_cfg(base_cfg):
    grid = [{"rsi_entry_threshold": 99}]
    fake = _fake_backtester_cls({99: 0.0})
    run_sweep(base_cfg, {}, grid, backtester_cls=fake)
    assert base_cfg["strategy"]["rsi_entry_threshold"] == 60


# ── report ────────────────────────────────────────────────────────────────────

def test_format_sweep_report_contains_params_and_metrics():
    results = [{"params": {"rsi_entry_threshold": 60}, "net_pnl": 900.0,
                "win_rate": 55.0, "profit_factor": 2.1,
                "max_drawdown": 1200.0, "trades": 14}]
    report = format_sweep_report(results)
    assert "rsi_entry_threshold" in report
    assert "900.00" in report
    assert "55.0%" in report


def test_format_sweep_report_handles_inf_profit_factor():
    results = [{"params": {}, "net_pnl": 100.0, "win_rate": 100.0,
                "profit_factor": float("inf"), "max_drawdown": 0.0, "trades": 2}]
    report = format_sweep_report(results)
    assert "inf" in report


# ── V2 P6: walk-forward validation ────────────────────────────────────────────

from src.param_sweep import walk_forward
import pandas as pd


def test_walk_forward_optimizes_in_sample_then_verifies_oos(base_cfg):
    df = pd.DataFrame({
        "timestamp": pd.date_range("2026-06-01 09:15", periods=20, freq="5min"),
        "open": [1.0] * 20, "high": [1.0] * 20, "low": [1.0] * 20,
        "close": [1.0] * 20, "volume": [1] * 20,
    })
    candles = {"X": df}
    grid = [{"rsi_entry_threshold": 55}, {"rsi_entry_threshold": 60},
            {"rsi_entry_threshold": 65}]
    fake = _fake_backtester_cls({55: 100.0, 60: 900.0, 65: 400.0})
    res = walk_forward(base_cfg, candles, grid, split=0.5, backtester_cls=fake)
    assert res["best_params"] == {"rsi_entry_threshold": 60}
    assert res["out_of_sample"]["net_pnl"] == 900.0


def test_walk_forward_handles_too_short_data(base_cfg):
    df = pd.DataFrame({"close": [1.0, 2.0, 3.0], "open": [1.0, 2.0, 3.0],
                       "high": [1.0, 2.0, 3.0], "low": [1.0, 2.0, 3.0], "volume": [1, 1, 1]})
    fake = _fake_backtester_cls({60: 0.0})
    res = walk_forward(base_cfg, {"X": df}, [{"rsi_entry_threshold": 60}],
                       backtester_cls=fake)
    # no usable split -> empty in-sample -> graceful result
    assert "best_params" in res
