"""
Whole-router backtest (regime router, commit 9).

Runs the FULL pipeline over history — MarketState -> regime -> route -> trade —
and scores it against the naive baselines it must beat to justify its complexity:
best-single-strategy and equal-weight-all. If routing doesn't win out-of-sample,
that is a valid finding and the router stays off (see docs/specs section 10).

The registry is empty today, so a live run trades nothing; this harness is exercised
with supplied signal functions (backtest/research). It is intentionally a compact,
self-contained simulator (one position per symbol, weight-scaled size) — enough to
compare routed vs baselines; the production Backtester remains the per-strategy engine.

`signal_fns[name](window_df) -> "BUY" | "SELL" | "HOLD"`.
"""
from typing import Callable, Optional

import pandas as pd

from src.market_state import compute_market_state
from src.regime import RegimeConfig, RegimeState, classify
from src.router import PremarketAllocation, RouterConfig, route


def regime_timeline(df: pd.DataFrame, regime_cfg: RegimeConfig,
                    ms_cfg: Optional[dict] = None) -> list:
    """RegimeState for every bar, computed only from bars up to that bar (no
    look-ahead), carrying the hysteresis state forward. O(n^2) — fine for backtests."""
    states, prev = [], None
    for i in range(len(df)):
        st = classify(compute_market_state(df.iloc[:i + 1], ms_cfg), prev, regime_cfg)
        states.append(st)
        prev = st
    return states


def _simulate_net(df: pd.DataFrame, signal_fn: Callable, weight_series: list,
                  window: int) -> float:
    """Long/short, one position at a time; size scaled by the per-bar weight.
    Returns net P&L (in weight-scaled price units)."""
    close = df["close"].values
    pos_dir = None
    entry = 0.0
    entry_w = 0.0
    net = 0.0
    for i in range(window, len(df)):
        sig = signal_fn(df.iloc[:i + 1])
        price = close[i]
        if pos_dir is not None:
            opposite = (pos_dir == "BUY" and sig == "SELL") or (pos_dir == "SELL" and sig == "BUY")
            if opposite:
                move = (price - entry) if pos_dir == "BUY" else (entry - price)
                net += move * entry_w
                pos_dir = None
        if pos_dir is None and sig in ("BUY", "SELL"):
            w = weight_series[i]
            if w > 0:
                pos_dir, entry, entry_w = sig, price, w
    if pos_dir is not None:                       # close at the last bar
        move = (close[-1] - entry) if pos_dir == "BUY" else (entry - close[-1])
        net += move * entry_w
    return round(net, 4)


def _combined_net(df, signal_fns: dict, weights: dict, window: int) -> float:
    return round(sum(_simulate_net(df, signal_fns[n], weights[n], window)
                     for n in signal_fns), 4)


def run_comparison(df: pd.DataFrame, metas: list, signal_fns: dict,
                   regime_cfg: RegimeConfig, router_cfg: RouterConfig,
                   premarket: PremarketAllocation, window: int = 60,
                   ms_cfg: Optional[dict] = None) -> dict:
    """Routed vs best-single vs equal-weight over `df`."""
    names = [m.name for m in metas]
    n_bars = len(df)

    # per-bar routed weights (the router's decision each bar)
    routed_weights = {n: [0.0] * n_bars for n in names}
    prev: dict = {}
    for i, st in enumerate(regime_timeline(df, regime_cfg, ms_cfg)):
        active = route(st, metas, premarket, router_cfg, prev)
        prev = {a.name: a.weight for a in active}
        for a in active:
            routed_weights[a.name][i] = a.weight

    routed = _combined_net(df, signal_fns, routed_weights, window) if names else 0.0
    singles = {n: _simulate_net(df, signal_fns[n], [1.0] * n_bars, window) for n in names}
    best_single = max(singles.values()) if singles else 0.0
    eq_w = 1.0 / len(names) if names else 0.0
    equal_weight = (_combined_net(df, signal_fns, {n: [eq_w] * n_bars for n in names}, window)
                    if names else 0.0)

    return {
        "routed": routed,
        "singles": singles,
        "best_single": best_single,
        "equal_weight": equal_weight,
        "routed_beats_best_single": routed > best_single,
        "routed_beats_equal_weight": routed > equal_weight,
        "bars": n_bars,
    }


def format_comparison(result: dict) -> str:
    lines = ["=" * 52, " REGIME ROUTER — walk-forward comparison", "=" * 52,
             f" Routed        : {result['routed']:>12.2f}",
             f" Best single   : {result['best_single']:>12.2f}",
             f" Equal weight  : {result['equal_weight']:>12.2f}",
             "-" * 52]
    for name, net in result.get("singles", {}).items():
        lines.append(f"   {name:<20} {net:>12.2f}")
    lines.append("-" * 52)
    verdict = ("routing BEATS both baselines" if result["routed_beats_best_single"]
               and result["routed_beats_equal_weight"]
               else "routing does NOT beat baselines — keep it off")
    lines.append(f" Verdict: {verdict}")
    lines.append("=" * 52)
    return "\n".join(lines)
