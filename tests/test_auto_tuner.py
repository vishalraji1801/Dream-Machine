import pandas as pd
import yaml

from src.overlay import load_overlay
from src.auto_tuner import (DEFAULT_GRIDS, _stable_params, format_report,
                            pick_winner, tune_strategy, write_overlay)
from src.backtester import BacktestResult, BacktestTrade


# ── stability pick ────────────────────────────────────────────────────────────

def _fold(params, n=1):
    return {"fold": n, "best_params": params, "in_sample_net": 100, "oos_net": 50,
            "oos_trades": 10}


def test_stable_params_majority_wins():
    folds = [_fold({"a": 1}), _fold({"a": 2}), _fold({"a": 1})]
    assert _stable_params(folds) == {"a": 1}


def test_stable_params_tie_prefers_recent():
    folds = [_fold({"a": 1}), _fold({"a": 2})]
    assert _stable_params(folds) == {"a": 2}      # tie -> most recent fold


def test_stable_params_empty():
    assert _stable_params([]) is None


# ── tune_strategy with a controllable backtester ──────────────────────────────

def _bt_trade(pnl, i=0):
    return BacktestTrade("X", "BUY", 1, 100.0, 100.0 + pnl,
                         pd.Timestamp("2026-06-01"),
                         pd.Timestamp("2026-06-01") + pd.Timedelta(minutes=5 * i),
                         pnl, "target_hit", costs=10.0)


class _TunableBT:
    """rsi_entry_threshold=60 is the consistently best parameter."""
    PNL = {55: 20.0, 60: 150.0, 65: 40.0}

    def __init__(self, cfg, window=60):
        self._p = cfg["strategy"].get("rsi_entry_threshold", 60)

    def run(self, candles, index_candles=None):
        trades = [_bt_trade(self.PNL.get(self._p, 0.0), i) for i in range(12)]
        return BacktestResult.from_trades(trades)


def test_tune_strategy_finds_stable_winner():
    df = pd.DataFrame({"open": [1.0] * 80, "high": [1.0] * 80, "low": [1.0] * 80,
                       "close": [1.0] * 80, "volume": [1] * 80})
    res = tune_strategy({"strategy": {}}, {"X": df}, "momentum_vwap_breakout",
                        grid_spec={"rsi_entry_threshold": [55, 60, 65]},
                        folds=3, backtester_cls=_TunableBT)
    assert res["params"] == {"rsi_entry_threshold": 60}
    assert res["stability"] == "3/3"
    assert res["oos_trades"] > 0


# ── acceptance bar ────────────────────────────────────────────────────────────

def _result(strategy="s", trades=50, net=1000.0, pf=1.5):
    return {"strategy": strategy, "params": {"a": 1}, "stability": "3/3",
            "oos_trades": trades, "oos_net": net, "oos_pf": pf,
            "oos_win_rate": 50.0, "oos_max_dd": 100.0,
            "in_sample_net_avg": 1200.0, "degradation_pct": 16.7}


def test_pick_winner_takes_best_passing():
    results = [_result("good", trades=60, net=2000, pf=1.5),
               _result("weak", trades=60, net=500, pf=1.25)]
    assert pick_winner(results)["strategy"] == "good"


def test_pick_winner_skips_thin_or_losing():
    results = [_result("thin", trades=5, net=9000, pf=3.0),     # too few OOS trades
               _result("losing", trades=200, net=-500, pf=0.9)]  # negative
    assert pick_winner(results) is None


def test_pick_winner_skips_low_pf():
    assert pick_winner([_result(trades=100, net=100, pf=1.05)]) is None


# ── overlay writing (validated, bounded) ──────────────────────────────────────

def _cfg(tmp_path):
    return {
        "trading": {"market_open": "09:15", "market_close": "15:30"},
        "strategy": {}, "risk": {},
        "overlay": {"overlay_enabled": True,
               "overlay_path": str(tmp_path / "overlay.yaml"),
               "allowed_strategies": ["breakout_retest", "supertrend"],
               "min_stop_loss_pct": 0.5, "max_stop_loss_pct": 2.0,
               "min_target_pct": 0.5, "max_target_pct": 5.0},
    }


def test_write_overlay_valid_and_loadable(tmp_path):
    cfg = _cfg(tmp_path)
    winner = _result("breakout_retest")
    winner["params"] = {"br_lookback": 20, "br_tol_pct": 0.3}
    written, msg = write_overlay(winner, cfg)
    assert written is True
    overlay, err = load_overlay(cfg)          # the bot's own loader accepts it
    assert err is None
    assert overlay["strategy"]["name"] == "breakout_retest"
    assert overlay["strategy"]["br_lookback"] == 20
    # meta recorded for auditability
    raw = yaml.safe_load(open(cfg["overlay"]["overlay_path"]))
    assert raw["meta"]["written_by"] == "auto_tuner"


def test_write_overlay_rejects_unlisted_strategy(tmp_path):
    cfg = _cfg(tmp_path)
    winner = _result("wild_martingale")
    written, msg = write_overlay(winner, cfg)
    assert written is False
    assert "allowed_strategies" in msg


def test_write_overlay_filters_non_adjustable_params(tmp_path):
    cfg = _cfg(tmp_path)
    winner = _result("supertrend")
    winner["params"] = {"supertrend_period": 10, "total_capital": 9999999}  # sneaky
    written, _ = write_overlay(winner, cfg)
    assert written is True
    overlay, err = load_overlay(cfg)
    assert err is None
    assert "total_capital" not in overlay["strategy"]     # filtered, not written


# ── grids & report ────────────────────────────────────────────────────────────

def test_every_grid_value_is_within_overlay_bounds(tmp_path):
    """Everything the tuner can propose must survive the overlay validator."""
    from src.overlay import _validate
    cfg = _cfg(tmp_path)
    cfg["overlay"]["allowed_strategies"] = list(DEFAULT_GRIDS)
    from src.param_sweep import expand_grid
    for strat, spec in DEFAULT_GRIDS.items():
        for combo in expand_grid(spec):
            overlay = {"strategy": {"name": strat, **combo}}
            assert _validate(overlay, cfg) is None, f"{strat} {combo}"


def test_format_report_mentions_winner_or_none():
    results = [_result("breakout_retest")]
    assert "WINNER: breakout_retest" in format_report(results, results[0], "15min", 30)
    assert "NO WINNER" in format_report(results, None, "15min", 30)
