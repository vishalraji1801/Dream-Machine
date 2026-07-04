"""
Backtest orchestrator (SCRUM-95).

Streamlines the whole loop: pick a stock set with the universe builder, ensure a
year of data for every timeframe is in the backtest store, run the strategy
across each timeframe, and produce a per-timeframe results summary that the
headless Claude analyst reads.
"""
import os
from datetime import datetime
from typing import Optional

from src.backtester import Backtester
from src.logger import get_logger

logger = get_logger("backtest_runner")


def load_all(loader, stocks: list[dict], index: Optional[dict] = None,
             force: bool = False) -> dict:
    """Ensure a year of every timeframe is stored for each stock (+ index)."""
    report = {}
    targets = list(stocks) + ([index] if index else [])
    for s in targets:
        report[s["symbol"]] = loader.load_symbol(s["symbol"], s["token"], force=force)
    return report


def run_across_timeframes(cfg: dict, store, symbols: list[str],
                          index_symbol: Optional[str] = None,
                          window: int = 60, backtester_cls=Backtester) -> list[dict]:
    """Run the configured strategy on every stored timeframe. One summary per TF."""
    timeframes = [tf["label"] for tf in cfg.get("backtest_data", {}).get(
        "timeframes", [])] or store_timeframes(store, symbols)
    summaries = []
    for tf in timeframes:
        candles = {}
        for sym in symbols:
            df = store.get_candles(sym, tf)
            if df is not None and not df.empty:
                candles[sym] = df
        if not candles:
            logger.warning(f"No data for timeframe {tf} — skipped")
            continue
        index_candles = store.get_candles(index_symbol, tf) if index_symbol else None
        result = backtester_cls(cfg, window=window).run(candles, index_candles=index_candles)
        summaries.append(_summarize(tf, candles, result))
    return summaries


def store_timeframes(store, symbols: list[str]) -> list[str]:
    seen = []
    for tf in ("1min", "5min", "15min", "30min", "1hr"):
        if any(store.candle_count(s, tf) > 0 for s in symbols):
            seen.append(tf)
    return seen


def _summarize(tf: str, candles: dict, result) -> dict:
    n = result.total_trades
    costs = round(sum(getattr(t, "costs", 0.0) for t in result.trades), 2)
    return {
        "timeframe": tf,
        "symbols": len(candles),
        "candles": sum(len(d) for d in candles.values()),
        "trades": n,
        "net_pnl": result.net_pnl,
        "win_rate": result.win_rate,
        "profit_factor": result.profit_factor,
        "max_drawdown": result.max_drawdown,
        "expectancy": round(result.net_pnl / n, 2) if n else 0.0,
        "est_costs": costs,
        "avg_cost": round(costs / n, 2) if n else 0.0,
    }


def format_summary(summaries: list[dict], strategy: str) -> str:
    lines = [
        f"# Backtest summary — {strategy} — {datetime.now():%Y-%m-%d}",
        "",
        "| TF | symbols | trades | net P&L | win% | PF | max DD | expectancy | avg cost |",
        "|----|--------|--------|---------|------|----|--------|------------|----------|",
    ]
    for s in summaries:
        pf = s["profit_factor"]
        pf_s = f"{pf}" if pf != float("inf") else "inf"
        lines.append(
            f"| {s['timeframe']} | {s['symbols']} | {s['trades']} | {s['net_pnl']} | "
            f"{s['win_rate']} | {pf_s} | {s['max_drawdown']} | {s['expectancy']} | {s['avg_cost']} |")
    lines.append("")
    lines.append("Note: expectancy vs avg cost is the key ratio; a trade count below "
                 "~100 per timeframe is not statistically conclusive.")
    return "\n".join(lines)


def write_summary(summaries: list[dict], strategy: str,
                  path: Optional[str] = None) -> str:
    path = path or os.path.join("logs", f"backtest_summary_{datetime.now():%Y-%m-%d}.md")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(format_summary(summaries, strategy))
    logger.info(f"Backtest summary written: {path}")
    return path
