"""
Parameter sweep — grid-search strategy parameters over the backtester.
Runs one backtest per parameter combination on the same candle data and
ranks results by net P&L.
"""
import copy
import itertools

from src.backtester import Backtester
from src.logger import get_logger

logger = get_logger("param_sweep")


def expand_grid(param_specs: dict[str, list]) -> list[dict]:
    """{'rsi_entry_threshold': [55, 60], 'volume_multiplier': [1.2, 1.5]}
    → [{rsi: 55, vol: 1.2}, {rsi: 55, vol: 1.5}, {rsi: 60, vol: 1.2}, ...]"""
    if not param_specs:
        return [{}]
    keys = list(param_specs)
    return [dict(zip(keys, combo))
            for combo in itertools.product(*param_specs.values())]


def run_sweep(cfg: dict, candles: dict, grid: list[dict],
              index_candles=None, window: int = 60,
              backtester_cls=Backtester) -> list[dict]:
    """Run one backtest per parameter combination. Results sorted by net P&L."""
    results = []
    for n, params in enumerate(grid, 1):
        c = copy.deepcopy(cfg)
        c["strategy"].update(params)
        logger.info(f"Sweep {n}/{len(grid)}: {params}")
        r = backtester_cls(c, window=window).run(candles, index_candles=index_candles)
        results.append({
            "params": params,
            "net_pnl": r.net_pnl,
            "win_rate": r.win_rate,
            "profit_factor": r.profit_factor,
            "max_drawdown": r.max_drawdown,
            "trades": r.total_trades,
        })
    results.sort(key=lambda x: x["net_pnl"], reverse=True)
    return results


def _split_candles(candles: dict, split: float):
    """Split each symbol's candles by row index into (in-sample, out-of-sample)."""
    in_s, out_s = {}, {}
    for sym, df in candles.items():
        cut = int(len(df) * split)
        if cut < 5 or len(df) - cut < 5:
            continue
        in_s[sym] = df.iloc[:cut].reset_index(drop=True)
        out_s[sym] = df.iloc[cut:].reset_index(drop=True)
    return in_s, out_s


def walk_forward(cfg: dict, candles: dict, grid: list[dict], split: float = 0.6,
                 index_candles=None, window: int = 60,
                 backtester_cls=Backtester) -> dict:
    """
    Guard against curve-fitting: optimise parameters on the in-sample window,
    then evaluate the winner on the untouched out-of-sample window. A strategy
    whose in-sample edge vanishes out-of-sample was fit to noise.
    """
    in_candles, out_candles = _split_candles(candles, split)
    idx_in = idx_out = None
    if index_candles is not None and len(index_candles):
        cut = int(len(index_candles) * split)
        idx_in = index_candles.iloc[:cut].reset_index(drop=True)
        idx_out = index_candles.iloc[cut:].reset_index(drop=True)

    ranked = run_sweep(cfg, in_candles, grid, index_candles=idx_in,
                       window=window, backtester_cls=backtester_cls)
    if not ranked:
        return {"best_params": None, "in_sample": None, "out_of_sample": None}

    best = ranked[0]
    import copy
    c = copy.deepcopy(cfg)
    c["strategy"].update(best["params"])
    oos = backtester_cls(c, window=window).run(out_candles, index_candles=idx_out)
    return {
        "best_params": best["params"],
        "in_sample": best,
        "out_of_sample": {
            "net_pnl": oos.net_pnl, "win_rate": oos.win_rate,
            "profit_factor": oos.profit_factor, "trades": oos.total_trades,
        },
    }


def format_sweep_report(results: list[dict]) -> str:
    """Ranked table of sweep results."""
    lines = [
        "=" * 100,
        " PARAMETER SWEEP RESULTS (ranked by net P&L)",
        "=" * 100,
        f" {'#':<3} {'net_pnl':>12} {'win_rate':>9} {'pf':>7} {'max_dd':>12} {'trades':>7}  params",
        "-" * 100,
    ]
    for i, r in enumerate(results, 1):
        pf = r["profit_factor"]
        pf_str = f"{pf:.2f}" if pf != float("inf") else "inf"
        lines.append(
            f" {i:<3} {r['net_pnl']:>12.2f} {r['win_rate']:>8.1f}% {pf_str:>7} "
            f"{r['max_drawdown']:>12.2f} {r['trades']:>7}  {r['params']}"
        )
    lines.append("=" * 100)
    return "\n".join(lines)
