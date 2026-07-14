from types import SimpleNamespace

import pandas as pd
import pytest

from src.backtester import BacktestResult, BacktestTrade
from src import validation as V


def _t(pnl, costs=80.0, day=1):
    return {"pnl": pnl, "costs": costs, "exit_time": f"2026-07-{day:02d} 11:00:00"}


# ── basic stats ───────────────────────────────────────────────────────────────

def test_expectancy_and_avg_cost():
    trades = [_t(100), _t(-40), _t(60)]
    assert V.expectancy(trades) == pytest.approx(40.0)
    assert V.avg_cost(trades) == 80.0


def test_max_drawdown():
    # equity: +500, -300 (dd 300), +100 (dd 200), -600 (dd 800)
    assert V.max_drawdown([500, -300, 100, -600]) == 800.0


def test_profit_factor():
    assert V.profit_factor([200, -100]) == 2.0
    assert V.profit_factor([100, 50]) == float("inf")


def test_percentile():
    vals = list(range(1, 101))  # 1..100
    assert V._percentile(vals, 5) == pytest.approx(5.95, abs=0.5)
    assert V._percentile(vals, 50) == pytest.approx(50.5, abs=0.5)


# ── Monte Carlo ───────────────────────────────────────────────────────────────

def test_monte_carlo_deterministic_with_seed():
    trades = [_t(x) for x in (100, -50, 80, -30, 120, -70, 40)]
    a = V.monte_carlo(trades, runs=200, seed=7)
    b = V.monte_carlo(trades, runs=200, seed=7)
    assert a == b
    assert a["p5_net"] <= a["median_net"]  # bad case <= median


def test_monte_carlo_empty():
    assert V.monte_carlo([])["runs"] == 0


# ── drop best trades ──────────────────────────────────────────────────────────

def test_drop_best_flips_negative_when_outlier_driven():
    trades = [_t(5000)] + [_t(-200) for _ in range(10)]  # one big winner carries it
    res = V.drop_best_trades(trades, n=1)
    assert res["net_full"] > 0
    assert res["net_after_drop"] < 0
    assert res["still_positive"] is False


def test_drop_best_survives_when_broad():
    trades = [_t(100) for _ in range(20)]
    res = V.drop_best_trades(trades, n=5)
    assert res["still_positive"] is True


# ── sub-period consistency ────────────────────────────────────────────────────

def test_sub_period_all_profitable():
    trades = [_t(100, day=d) for d in range(1, 10)]
    res = V.sub_period_consistency(trades, periods=3)
    assert res["profitable_periods"] == 3
    assert len(res["net_by_period"]) == 3


def test_sub_period_one_hot_period():
    # first third big winners, rest losers
    trades = ([_t(1000, day=1) for _ in range(3)]
              + [_t(-100, day=5) for _ in range(3)]
              + [_t(-100, day=9) for _ in range(3)])
    res = V.sub_period_consistency(trades, periods=3)
    assert res["profitable_periods"] == 1


# ── parameter plateau ─────────────────────────────────────────────────────────

def _sweep(mapping):
    return [{"params": {"rsi": k}, "net_pnl": v} for k, v in mapping.items()]


def test_plateau_true_when_neighbors_profitable():
    sweep = _sweep({55: 400, 60: 900, 65: 500})
    res = V.parameter_plateau(sweep, {"rsi": 60})
    assert res["is_plateau"] is True
    assert res["total_neighbors"] == 2


def test_plateau_false_when_spike():
    sweep = _sweep({55: -300, 60: 900, 65: -200})  # lone spike at 60
    res = V.parameter_plateau(sweep, {"rsi": 60})
    assert res["is_plateau"] is False
    assert res["profitable_neighbors"] == 0


# ── cost/slippage stress (fake backtester) ────────────────────────────────────

class _FakeResult:
    def __init__(self, pf, trades=10, net=1000.0):
        self.profit_factor = pf
        self.total_trades = trades
        self.net_pnl = net
        self.win_rate = 55.0
        self.max_drawdown = 200.0
        self.trades = []


class _FakeBT:
    def __init__(self, cfg, window=60):
        self._pf = cfg.get("_fake_pf", 1.5)

    def run(self, candles, index_candles=None):
        return _FakeResult(self._pf)


def test_cost_stress_survives():
    cfg = {"strategy": {}, "costs": {}, "backtest": {}, "_fake_pf": 1.5}
    res = V.cost_slippage_stress(cfg, {"X": None}, backtester_cls=_FakeBT)
    assert res["survives"] is True


def test_cost_stress_dies():
    cfg = {"strategy": {}, "costs": {}, "backtest": {}, "_fake_pf": 1.05}
    res = V.cost_slippage_stress(cfg, {"X": None}, backtester_cls=_FakeBT)
    assert res["survives"] is False


def test_cost_stress_sets_next_open_and_scales_costs():
    seen = {}

    class SpyBT:
        def __init__(self, cfg, window=60):
            seen["costs"] = cfg["costs"]
            seen["backtest"] = cfg["backtest"]
        def run(self, candles, index_candles=None):
            return _FakeResult(1.4)

    cfg = {"strategy": {}, "costs": {"brokerage_pct": 0.03}, "backtest": {}}
    V.cost_slippage_stress(cfg, {"X": None}, cost_mult=1.5, slippage_pct=0.1, backtester_cls=SpyBT)
    assert seen["costs"]["brokerage_pct"] == pytest.approx(0.045)  # 0.03 * 1.5
    assert seen["backtest"]["fill_mode"] == "next_open"
    assert seen["backtest"]["slippage_pct"] == 0.1


# ── rolling walk-forward (fake backtester returning real trades) ──────────────

def _bt_trade(pnl, i=0):
    return BacktestTrade("X", "BUY", 1, 100.0, 100.0 + pnl, pd.Timestamp("2026-06-01"),
                         pd.Timestamp("2026-06-01") + pd.Timedelta(minutes=5 * i),
                         pnl, "target_hit", costs=10.0)


class _WFBacktester:
    """Net P&L depends on the rsi param, so the sweep has something to choose."""
    PNL_BY_RSI = {55: 50.0, 60: 200.0, 65: 90.0}

    def __init__(self, cfg, window=60):
        self._rsi = cfg["strategy"].get("rsi", 60)

    def run(self, candles, index_candles=None):
        pnl = self.PNL_BY_RSI.get(self._rsi, 0.0)
        trades = [_bt_trade(pnl, i) for i in range(2)]
        return BacktestResult.from_trades(trades)


def test_walk_forward_picks_best_and_stitches_oos():
    df = pd.DataFrame({"open": [1.0] * 60, "high": [1.0] * 60, "low": [1.0] * 60,
                       "close": [1.0] * 60, "volume": [1] * 60})
    candles = {"X": df}
    grid = [{"rsi": 55}, {"rsi": 60}, {"rsi": 65}]
    wf = V.walk_forward_rolling({"strategy": {}}, candles, grid, folds=2,
                                backtester_cls=_WFBacktester)
    assert len(wf["folds"]) == 2
    # each fold should pick rsi=60 (highest net) and produce 2 OOS trades
    for fold in wf["folds"]:
        assert fold["best_params"] == {"rsi": 60}
    assert wf["oos_result"].total_trades == 4  # 2 folds x 2 trades


# ── paper vs backtest ─────────────────────────────────────────────────────────

def test_paper_matches_backtest():
    paper = [_t(100), _t(90), _t(110)]  # expectancy 100
    res = V.compare_paper_vs_backtest(paper, backtest_expectancy=105.0)
    assert res["reliable"] is True
    assert res["divergence_pct"] < 30


def test_paper_diverges_from_backtest():
    paper = [_t(20), _t(30), _t(10)]  # expectancy 20
    res = V.compare_paper_vs_backtest(paper, backtest_expectancy=100.0)
    assert res["reliable"] is False
    assert res["divergence_pct"] == 80.0


# ── scorecard ─────────────────────────────────────────────────────────────────

def _result(trades_list, net, pf, dd):
    return SimpleNamespace(trades=trades_list, total_trades=len(trades_list),
                           net_pnl=net, profit_factor=pf, max_drawdown=dd)


def test_scorecard_all_pass():
    trades = [_t(200, costs=50) for _ in range(120)]
    result = _result(trades, net=24000, pf=1.6, dd=3000)
    report = V.scorecard(
        result,
        monte={"p5_net": 500, "median_net": 24000, "p95_max_drawdown": 5000},
        sub={"profitable_periods": 3, "net_by_period": [1, 1, 1]},
        plateau={"is_plateau": True, "profitable_neighbors": 2, "total_neighbors": 2},
        stress={"survives": True, "profit_factor": 1.3},
        drop={"still_positive": True, "net_after_drop": 20000, "dropped": 5, "net_full": 24000},
    )
    assert report["ready"] is True


def test_scorecard_fails_on_low_trade_count():
    trades = [_t(200, costs=50) for _ in range(30)]
    result = _result(trades, net=6000, pf=1.6, dd=500)
    report = V.scorecard(result)
    assert report["ready"] is False
    assert report["checks"]["trade_count"][0] is False


def test_scorecard_fails_on_expectancy_below_2x_cost():
    # expectancy 80, avg cost 80 -> need >=160 -> fails (the baseline danger zone)
    trades = [_t(80, costs=80) for _ in range(120)]
    result = _result(trades, net=9600, pf=1.4, dd=1000)
    report = V.scorecard(result)
    assert report["checks"]["expectancy_vs_cost"][0] is False


def test_scorecard_fails_on_wide_drawdown():
    trades = [_t(100, costs=50) for _ in range(120)]
    # net 12000, dd 9000 -> ratio 0.75 > 0.20
    result = _result(trades, net=12000, pf=1.4, dd=9000)
    report = V.scorecard(result)
    assert report["checks"]["drawdown_vs_profit"][0] is False


def test_format_scorecard_contains_verdict():
    trades = [_t(200, costs=50) for _ in range(120)]
    report = V.scorecard(_result(trades, 24000, 1.6, 2000))
    text = V.format_scorecard(report, title="momentum")
    assert "SCORECARD" in text and "VERDICT" in text
