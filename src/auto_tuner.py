"""
Auto-tuner (SCRUM-103) — backtest + sweep + AI, integrated.

For each strategy it runs a WALK-FORWARD parameter sweep (never a plain
in-sample sweep — parameters that only win on the data they were fitted to are
noise), picks the most *stable* fold-winning parameters, and, if the stitched
out-of-sample result clears the bar, writes the winner into
config/ai_overlay.yaml.

The overlay is the safe channel: main.py validates every field against hard
bounds at startup and falls back to config.yaml on any violation — so the
auto-tuner can adjust indicator parameters and switch strategies, but can never
push the bot outside limits defined in code. The headless Claude reviewer then
audits the decision and may veto (rewrite the overlay to a no-op) — it cannot
exceed the same bounds.
"""
import copy
from collections import Counter
from datetime import datetime
from typing import Optional

import yaml

from src.ai_overlay import _validate
from src.backtester import Backtester
from src.logger import get_logger
from src.param_sweep import expand_grid
from src.validation import walk_forward_rolling

logger = get_logger("auto_tuner")

# Small, bounded grids per strategy (all values inside the overlay hard bounds).
DEFAULT_GRIDS: dict[str, dict[str, list]] = {
    "momentum_vwap_breakout": {"rsi_entry_threshold": [55, 60, 65],
                               "volume_multiplier": [1.2, 1.5, 2.0]},
    "vwap_mean_reversion":    {"vwap_stretch_pct": [1.0, 1.5, 2.0],
                               "rsi_oversold": [25, 30, 35]},
    "orb":                    {"orb_end": ["09:30", "09:45"],
                               "volume_multiplier": [1.2, 1.5]},
    "supertrend":             {"supertrend_period": [7, 10, 14],
                               "supertrend_mult": [2.0, 3.0, 4.0]},
    "ema_crossover":          {"ec_fast": [10, 20], "ec_slow": [50, 100]},
    "rsi_reversal":           {"rsi_rev_period": [2, 5],
                               "rsi_rev_oversold": [10, 20],
                               "rsi_rev_overbought": [80, 90]},
    "ema_pullback":           {"pullback_ema": [20, 50],
                               "pullback_tol_pct": [0.2, 0.4]},
    "breakout_retest":        {"br_lookback": [10, 20, 30],
                               "br_tol_pct": [0.2, 0.3, 0.5]},
    "macd_divergence":        {"macd_div_lookback": [14, 20, 30]},
    "support_resistance":     {"sr_lookback": [20, 30, 50],
                               "sr_tol_pct": [0.2, 0.3]},
    "price_action_levels":    {"pa_lookback": [10, 20, 30]},
    "swing_mtf":              {"mtf_long_ema": [50, 100],
                               "mtf_short_ema": [10, 20]},
    "smc":                    {"smc_lookback": [10, 20, 30]},
}

# Bar an auto-selected winner must clear on stitched OUT-OF-SAMPLE trades.
DEFAULT_ACCEPT = {"min_oos_trades": 30, "min_oos_pf": 1.2, "min_oos_net": 0.0}


def _stable_params(folds: list[dict]) -> Optional[dict]:
    """Most frequently chosen fold-winning params (ties -> most recent fold).
    A parameter set that wins across folds is stability evidence; one that wins
    a single fold is noise."""
    if not folds:
        return None
    counts = Counter(frozenset(f["best_params"].items()) for f in folds)
    top = max(counts.values())
    for f in reversed(folds):                      # most recent first on ties
        if counts[frozenset(f["best_params"].items())] == top:
            return f["best_params"]
    return folds[-1]["best_params"]


def tune_strategy(cfg: dict, candles: dict, strategy: str,
                  grid_spec: Optional[dict] = None, folds: int = 3,
                  index_candles=None, window: int = 60,
                  backtester_cls=Backtester) -> dict:
    """Walk-forward tune one strategy. Returns params, OOS stats, stability."""
    spec = grid_spec if grid_spec is not None else DEFAULT_GRIDS.get(strategy, {})
    grid = expand_grid(spec)
    c = copy.deepcopy(cfg)
    c.setdefault("strategy", {})["name"] = strategy

    wf = walk_forward_rolling(c, candles, grid, folds=folds,
                              index_candles=index_candles, window=window,
                              backtester_cls=backtester_cls)
    oos = wf["oos_result"]
    params = _stable_params(wf["folds"])
    wins = (sum(1 for f in wf["folds"]
                if frozenset(f["best_params"].items()) == frozenset((params or {}).items()))
            if params else 0)
    return {
        "strategy": strategy,
        "params": params or {},
        "stability": f"{wins}/{len(wf['folds'])}" if wf["folds"] else "0/0",
        "oos_trades": oos.total_trades,
        "oos_net": oos.net_pnl,
        "oos_pf": oos.profit_factor,
        "oos_win_rate": oos.win_rate,
        "oos_max_dd": oos.max_drawdown,
        "in_sample_net_avg": wf["in_sample_net_avg"],
        "degradation_pct": wf["degradation_pct"],
    }


def tune_all(cfg: dict, candles: dict, strategies: list[str], folds: int = 3,
             index_candles=None, window: int = 60,
             backtester_cls=Backtester) -> list[dict]:
    """Tune every strategy; return results sorted by OOS net P&L (best first)."""
    results = []
    for strat in strategies:
        logger.info(f"Auto-tuning '{strat}' (walk-forward, {folds} folds)")
        results.append(tune_strategy(cfg, candles, strat, folds=folds,
                                     index_candles=index_candles, window=window,
                                     backtester_cls=backtester_cls))
    results.sort(key=lambda r: r["oos_net"], reverse=True)
    return results


def pick_winner(results: list[dict], accept: Optional[dict] = None) -> Optional[dict]:
    """Best OOS result that clears the acceptance bar, else None."""
    a = {**DEFAULT_ACCEPT, **(accept or {})}
    for r in results:
        pf_ok = (r["oos_pf"] >= a["min_oos_pf"]) if r["oos_pf"] != float("inf") \
            else r["oos_trades"] > 0
        if (r["oos_trades"] >= a["min_oos_trades"] and pf_ok
                and r["oos_net"] > a["min_oos_net"]):
            return r
    return None


def write_overlay(winner: dict, cfg: dict,
                  path: Optional[str] = None) -> tuple[bool, str]:
    """
    Write the winner into the AI overlay. The overlay is validated with the
    same hard-bounds validator the bot uses at startup; an invalid overlay is
    NOT written. Returns (written, message).
    """
    from src.ai_overlay import _ADJUSTABLE
    adjustable = _ADJUSTABLE["strategy"]
    params = {k: v for k, v in winner["params"].items() if k in adjustable}

    overlay = {"strategy": {"name": winner["strategy"], **params}}
    err = _validate(overlay, cfg)
    if err:
        return False, f"overlay rejected by validator: {err}"

    doc = {
        "meta": {
            "written_by": "auto_tuner",
            "date": f"{datetime.now():%Y-%m-%d}",
            "stability": winner["stability"],
            "oos": {"trades": winner["oos_trades"], "net": winner["oos_net"],
                    "pf": winner["oos_pf"]},
        },
        **overlay,
    }
    path = path or cfg.get("ai", {}).get("overlay_path", "config/ai_overlay.yaml")
    with open(path, "w", encoding="utf-8") as f:
        f.write("# Written by auto_tuner — walk-forward OOS winner. The bot validates\n"
                "# every field against hard bounds at startup (src/ai_overlay.py).\n")
        yaml.safe_dump(doc, f, sort_keys=False)
    logger.warning(f"Overlay updated by auto-tuner: {winner['strategy']} {params}")
    return True, f"overlay written: {winner['strategy']} {params}"


def format_report(results: list[dict], winner: Optional[dict],
                  timeframe: str, symbols: int) -> str:
    lines = [
        f"# Auto-tune report — {datetime.now():%Y-%m-%d} — {timeframe}, {symbols} symbols",
        "",
        "All numbers are stitched OUT-OF-SAMPLE (walk-forward). In-sample is shown",
        "only to expose curve-fit degradation.",
        "",
        "| Strategy | params | stability | OOS trades | OOS net | OOS PF | win% | max DD | degr% |",
        "|----------|--------|-----------|-----------|---------|--------|------|--------|-------|",
    ]
    for r in results:
        pf = r["oos_pf"]
        lines.append(
            f"| {r['strategy']} | {r['params']} | {r['stability']} | {r['oos_trades']} | "
            f"{r['oos_net']} | {pf if pf != float('inf') else 'inf'} | {r['oos_win_rate']} | "
            f"{r['oos_max_dd']} | {r['degradation_pct']} |")
    lines.append("")
    if winner:
        lines.append(f"WINNER: {winner['strategy']} {winner['params']} -> written to ai_overlay.yaml")
    else:
        lines.append("NO WINNER: no strategy cleared the OOS acceptance bar "
                     "(trades>=30, PF>=1.2, net>0). Overlay left untouched.")
    return "\n".join(lines)
