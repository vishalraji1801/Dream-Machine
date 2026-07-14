"""
Strategy validation pipeline (SCRUM-85..91).

Turns a raw backtest into a statistically honest verdict. The baseline problem:
59 trades at 52.5% win rate is indistinguishable from a coin flip (std error
~6.5%), and expectancy (~Rs.83/trade) is barely one cost-unit wide. These tools
answer "can we actually tell if there's an edge?" — not just "was it profitable?"

Functions operate on a list of trades (BacktestTrade objects OR dicts) exposing
`pnl`, `costs`, and `exit_time`. Everything here is pure and deterministic
(Monte Carlo takes a seed) so the weekly Claude researcher can run it headless.
"""
import copy
import random
from typing import Optional

from src.backtester import Backtester
from src.costs import _DEFAULTS as _COST_DEFAULTS
from src.logger import get_logger
from src.param_sweep import run_sweep

logger = get_logger("validation")


# ── trade accessors (work on objects or dicts) ────────────────────────────────

def _f(t, attr):
    return getattr(t, attr) if hasattr(t, attr) else t[attr]


def pnls_of(trades) -> list:
    return [_f(t, "pnl") for t in trades]


def costs_of(trades) -> list:
    return [_f(t, "costs") for t in trades]


# ── basic stats ───────────────────────────────────────────────────────────────

def expectancy(trades) -> float:
    """Average P&L per trade (net of costs)."""
    p = pnls_of(trades)
    return round(sum(p) / len(p), 2) if p else 0.0


def avg_cost(trades) -> float:
    c = costs_of(trades)
    return round(sum(c) / len(c), 2) if c else 0.0


def max_drawdown(pnls: list) -> float:
    """Peak-to-trough drawdown of the cumulative equity curve."""
    equity = peak = dd = 0.0
    for p in pnls:
        equity += p
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
    return round(dd, 2)


def profit_factor(pnls: list) -> float:
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p <= 0))
    if gl > 0:
        return round(gp / gl, 2)
    return float("inf") if gp > 0 else 0.0


def _percentile(sorted_vals: list, pct: float) -> float:
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * pct / 100
    lo, hi = int(k), min(int(k) + 1, len(sorted_vals) - 1)
    frac = k - lo
    return round(sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac, 2)


# ── Stage 3 robustness: Monte Carlo, drop-best, sub-period ────────────────────

def monte_carlo(trades, runs: int = 1000, seed: int = 42) -> dict:
    """
    Bootstrap-resample the trade P&Ls (with replacement) `runs` times to see the
    plausible bad-luck outcome of the SAME underlying edge. Returns the 5th
    percentile net P&L (bad case) and 95th percentile max drawdown (bad case).
    """
    p = pnls_of(trades)
    if not p:
        return {"p5_net": 0.0, "median_net": 0.0, "p95_max_drawdown": 0.0, "runs": 0}
    rng = random.Random(seed)
    n = len(p)
    nets, dds = [], []
    for _ in range(runs):
        sample = [p[rng.randrange(n)] for _ in range(n)]
        nets.append(sum(sample))
        dds.append(max_drawdown(sample))
    nets.sort()
    dds.sort()
    return {
        "p5_net": _percentile(nets, 5),
        "median_net": _percentile(nets, 50),
        "p95_max_drawdown": _percentile(dds, 95),
        "runs": runs,
    }


def drop_best_trades(trades, n: int = 5) -> dict:
    """Remove the top-n winners. If net flips negative, the 'edge' was outliers."""
    p = sorted(pnls_of(trades), reverse=True)
    kept = p[n:]
    net_full = round(sum(p), 2)
    net_dropped = round(sum(kept), 2)
    return {
        "dropped": min(n, len(p)),
        "net_full": net_full,
        "net_after_drop": net_dropped,
        "still_positive": net_dropped > 0,
    }


def sub_period_consistency(trades, periods: int = 3) -> dict:
    """Split trades chronologically into thirds; count profitable sub-periods."""
    ordered = sorted(trades, key=lambda t: _f(t, "exit_time"))
    n = len(ordered)
    if n < periods:
        return {"periods": periods, "net_by_period": [], "profitable_periods": 0}
    size = n // periods
    nets = []
    for i in range(periods):
        start = i * size
        end = (i + 1) * size if i < periods - 1 else n
        nets.append(round(sum(pnls_of(ordered[start:end])), 2))
    return {
        "periods": periods,
        "net_by_period": nets,
        "profitable_periods": sum(1 for x in nets if x > 0),
    }


# ── Stage 3 robustness: parameter plateau & cost/slippage stress ──────────────

def parameter_plateau(sweep_results: list, chosen_params: dict) -> dict:
    """
    A real edge sits on a plateau: params adjacent to the winner in the sweep grid
    stay profitable. A fake edge is a lone spike. `sweep_results` is the list from
    run_sweep (each has 'params' and 'net_pnl').
    """
    by_key = {frozenset(r["params"].items()): r["net_pnl"] for r in sweep_results}
    keys = sorted({k for r in sweep_results for k in r["params"]})
    values = {k: sorted({r["params"][k] for r in sweep_results}) for k in keys}

    neighbors = []
    for k in keys:
        if k not in chosen_params:
            continue
        vals = values[k]
        try:
            idx = vals.index(chosen_params[k])
        except ValueError:
            continue
        for j in (idx - 1, idx + 1):
            if 0 <= j < len(vals):
                np_ = dict(chosen_params)
                np_[k] = vals[j]
                key = frozenset(np_.items())
                if key in by_key:
                    neighbors.append({"params": np_, "net_pnl": by_key[key]})
    profitable = [nb for nb in neighbors if nb["net_pnl"] > 0]
    return {
        "neighbors": neighbors,
        "profitable_neighbors": len(profitable),
        "total_neighbors": len(neighbors),
        "is_plateau": len(neighbors) > 0 and len(profitable) == len(neighbors),
    }


def cost_slippage_stress(cfg: dict, candles: dict, params: Optional[dict] = None,
                         index_candles=None, window: int = 60,
                         cost_mult: float = 1.5, slippage_pct: float = 0.1,
                         backtester_cls=Backtester) -> dict:
    """
    Re-run the backtest with 1.5x costs and a 2x-ish slippage penalty (next-open
    fills). Since the baseline edge is ~1 cost-unit wide, surviving this is the
    single most important deployability test.
    """
    c = copy.deepcopy(cfg)
    if params:
        c.setdefault("strategy", {}).update(params)
    costs = c.setdefault("costs", {})
    costs["enabled"] = True
    for k in ("brokerage_pct", "brokerage_cap", "stt_sell_pct", "exchange_txn_pct",
              "sebi_pct", "stamp_buy_pct"):
        costs[k] = costs.get(k, _COST_DEFAULTS[k]) * cost_mult
    bt = c.setdefault("backtest", {})
    bt["fill_mode"] = "next_open"
    bt["slippage_pct"] = slippage_pct

    result = backtester_cls(c, window=window).run(candles, index_candles=index_candles)
    return {
        "net_pnl": result.net_pnl,
        "profit_factor": result.profit_factor,
        "trades": result.total_trades,
        "survives": (result.profit_factor != float("inf") and result.profit_factor > 1.1)
                    or (result.profit_factor == float("inf") and result.total_trades > 0),
    }


# ── Stage 2: rolling (anchored) walk-forward ──────────────────────────────────

def _chunk_bounds(n: int, folds: int) -> list:
    """Contiguous (start, end) bounds for folds+1 chunks across n rows."""
    size = n // (folds + 1)
    bounds = []
    for i in range(folds + 1):
        start = i * size
        end = (i + 1) * size if i < folds else n
        bounds.append((start, end))
    return bounds


def walk_forward_rolling(cfg: dict, candles: dict, grid: list, folds: int = 4,
                         index_candles=None, window: int = 60,
                         backtester_cls=Backtester) -> dict:
    """
    Anchored walk-forward: for each fold, sweep parameters on all data up to the
    fold, freeze the winner, then evaluate on the NEXT (unseen) segment. Only the
    stitched out-of-sample trades are trusted. Big in-sample vs OOS gaps mean the
    sweep was fitting noise — the most common way retail strategies die.
    """
    from src.backtester import BacktestResult

    oos_trades, fold_reports, in_sample_nets = [], [], []
    for i in range(folds):
        train_c, test_c = {}, {}
        for sym, df in candles.items():
            b = _chunk_bounds(len(df), folds)
            train_end = b[i][1]
            test_start, test_end = b[i + 1]
            if train_end < 10 or (test_end - test_start) < 5:
                continue
            train_c[sym] = df.iloc[:train_end].reset_index(drop=True)
            test_c[sym] = df.iloc[test_start:test_end].reset_index(drop=True)
        if not train_c or not test_c:
            continue

        idx_train = idx_test = None
        if index_candles is not None and len(index_candles):
            b = _chunk_bounds(len(index_candles), folds)
            idx_train = index_candles.iloc[:b[i][1]].reset_index(drop=True)
            idx_test = index_candles.iloc[b[i + 1][0]:b[i + 1][1]].reset_index(drop=True)

        ranked = run_sweep(cfg, train_c, grid, index_candles=idx_train,
                           window=window, backtester_cls=backtester_cls)
        if not ranked:
            continue
        best = ranked[0]
        c = copy.deepcopy(cfg)
        c.setdefault("strategy", {}).update(best["params"])
        test_result = backtester_cls(c, window=window).run(test_c, index_candles=idx_test)
        oos_trades.extend(test_result.trades)
        in_sample_nets.append(best["net_pnl"])
        fold_reports.append({
            "fold": i + 1, "best_params": best["params"],
            "in_sample_net": best["net_pnl"], "oos_net": test_result.net_pnl,
            "oos_trades": test_result.total_trades,
        })

    stitched = BacktestResult.from_trades(oos_trades)
    in_avg = round(sum(in_sample_nets) / len(in_sample_nets), 2) if in_sample_nets else 0.0
    return {
        "oos_result": stitched,
        "folds": fold_reports,
        "in_sample_net_avg": in_avg,
        "oos_net": stitched.net_pnl,
        "degradation_pct": round((1 - stitched.net_pnl / in_avg) * 100, 1) if in_avg > 0 else None,
    }


# ── Stage 4: paper vs backtest ────────────────────────────────────────────────

def compare_paper_vs_backtest(paper_trades, backtest_expectancy: float,
                              tolerance: float = 0.30) -> dict:
    """
    Compare paper-trade expectancy against the backtest's expectation. A gap over
    ~30% means the backtest fill model is lying — fix it before trusting anything.
    """
    pe = expectancy(paper_trades)
    if backtest_expectancy:
        divergence = abs(pe - backtest_expectancy) / abs(backtest_expectancy)
    else:
        divergence = 0.0 if pe == 0 else float("inf")
    return {
        "paper_expectancy": pe,
        "backtest_expectancy": round(backtest_expectancy, 2),
        "divergence_pct": round(divergence * 100, 1) if divergence != float("inf") else None,
        "reliable": divergence <= tolerance,
    }


# ── The scorecard ─────────────────────────────────────────────────────────────

_THRESHOLDS = {
    "min_trades": 100,
    "min_profit_factor": 1.3,
    "expectancy_cost_mult": 2.0,
    "max_drawdown_ratio": 0.20,   # max DD <= 20% of net profit
    "min_profitable_periods": 2,  # of 3
    "stress_min_pf": 1.1,
}


def scorecard(result, monte=None, sub=None, plateau=None, stress=None, drop=None,
              thresholds: Optional[dict] = None) -> dict:
    """Evaluate a (preferably out-of-sample) result against all pass thresholds."""
    t = {**_THRESHOLDS, **(thresholds or {})}
    trades = result.trades
    n = result.total_trades
    exp = expectancy(trades)
    ac = avg_cost(trades)
    net = result.net_pnl
    pf = result.profit_factor
    dd = result.max_drawdown

    checks = {}
    checks["trade_count"] = (n >= t["min_trades"], n, f">={t['min_trades']}")
    pf_ok = pf >= t["min_profit_factor"] if pf != float("inf") else n > 0
    checks["profit_factor"] = (pf_ok, pf, f">={t['min_profit_factor']}")
    exp_need = round(t["expectancy_cost_mult"] * ac, 2)
    checks["expectancy_vs_cost"] = (exp >= exp_need if ac > 0 else exp > 0, exp, f">={exp_need}")
    dd_ratio = round(dd / net, 2) if net > 0 else None
    checks["drawdown_vs_profit"] = (net > 0 and dd_ratio is not None and dd_ratio <= t["max_drawdown_ratio"],
                                    dd_ratio, f"<={t['max_drawdown_ratio']}")
    if sub is not None:
        checks["sub_period_consistency"] = (sub["profitable_periods"] >= t["min_profitable_periods"],
                                            sub["profitable_periods"], f">={t['min_profitable_periods']}/3")
    if plateau is not None:
        checks["parameter_plateau"] = (plateau["is_plateau"],
                                       f"{plateau['profitable_neighbors']}/{plateau['total_neighbors']}", "all")
    if stress is not None:
        checks["survives_stress"] = (stress["survives"], stress["profit_factor"], f">{t['stress_min_pf']}")
    if drop is not None:
        checks["drop_best_trades"] = (drop["still_positive"], drop["net_after_drop"], ">0")
    if monte is not None:
        checks["monte_carlo_p5"] = (monte["p5_net"] > 0, monte["p5_net"], ">0")

    return {
        "ready": all(passed for passed, *_ in checks.values()),
        "checks": checks,
        "summary": {"trades": n, "net_pnl": net, "profit_factor": pf,
                    "expectancy": exp, "avg_cost": ac, "max_drawdown": dd},
    }


def format_scorecard(report: dict, title: str = "") -> str:
    lines = ["=" * 66, f" STRATEGY SCORECARD{(' — ' + title) if title else ''}", "=" * 66]
    for name, (passed, actual, need) in report["checks"].items():
        mark = "PASS" if passed else "FAIL"
        lines.append(f" [{mark}] {name:<24} actual={actual}  need {need}")
    lines.append("-" * 66)
    lines.append(f" VERDICT: {'EDGE CONFIRMED (paper-trade next)' if report['ready'] else 'NOT PROVEN — do not deploy'}")
    lines.append("=" * 66)
    return "\n".join(lines)
