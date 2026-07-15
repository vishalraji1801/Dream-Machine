"""
Auto-tune CLI — integrated backtest + walk-forward parameter sweep.

Runs offline from the backtest store (no Kite needed once data exists):
  1. walk-forward tune every strategy's parameters
  2. pick the most stable OOS-passing winner
  3. write it to config/overlay.yaml (validated, bounded) unless --dry-run

Usage:
  python bot.py tune                          # tune all strategies on 15min
  python bot.py tune --timeframe 30min --strategies supertrend
  python bot.py tune --dry-run                # report only, touch nothing
"""
import argparse
import os
import sys

import yaml

from src.auto_tuner import (DEFAULT_GRIDS, format_report, pick_winner,
                            tune_all, write_overlay)
from src.backtest_store import BacktestStore
from src.logger import get_logger, setup_logging

logger = get_logger("autotune")


def main() -> int:
    ap = argparse.ArgumentParser(description="Walk-forward auto-tuner (writes the config overlay)")
    ap.add_argument("--timeframe", default="15min",
                    choices=["1min", "5min", "15min", "30min", "1hr"])
    ap.add_argument("--strategies", default="",
                    help="comma list (default: all with a defined grid)")
    ap.add_argument("--folds", type=int, default=3)
    ap.add_argument("--window", type=int, default=60)
    ap.add_argument("--dry-run", action="store_true", help="report only; do not write the overlay")
    args = ap.parse_args()

    with open(os.path.join("config", "config.yaml")) as f:
        cfg = yaml.safe_load(f)
    setup_logging(level=cfg["logging"]["level"], retention_days=cfg["logging"]["retention_days"])

    strategies = ([s.strip() for s in args.strategies.split(",") if s.strip()]
                  or list(DEFAULT_GRIDS))
    unknown = [s for s in strategies if s not in DEFAULT_GRIDS]
    if unknown:
        print(f"ERROR: no tuning grid for: {unknown}. Known: {list(DEFAULT_GRIDS)}")
        return 1

    store = BacktestStore(cfg["backtest_data"].get("store_path",
                                                   os.path.join("data_cache", "backtest_data.db")))
    symbols = sorted(set(store.symbols(args.timeframe)) & set(cfg["trading"]["watchlist"]))
    if not symbols:
        print("ERROR: no stored stock data for this timeframe. Run `bot backtest` first.")
        return 1
    candles = {s: store.get_candles(s, args.timeframe) for s in symbols}
    candles = {s: df for s, df in candles.items() if df is not None and not df.empty}
    index_symbol = cfg["strategy"].get("regime_index_symbol", "NIFTY 50")
    index_candles = store.get_candles(index_symbol, args.timeframe)

    print(f"Auto-tuning {len(strategies)} strategies on {args.timeframe} "
          f"({len(candles)} symbols, {args.folds} folds, walk-forward)...")
    results = tune_all(cfg, candles, strategies, folds=args.folds,
                       index_candles=index_candles, window=args.window)
    winner = pick_winner(results)

    report = format_report(results, winner, args.timeframe, len(candles))
    report_path = os.path.join("logs", f"tuning_report_{__import__('datetime').datetime.now():%Y-%m-%d}.md")
    os.makedirs("logs", exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print("\n" + report)
    print(f"\nReport written: {report_path}")

    if winner and not args.dry_run:
        written, msg = write_overlay(winner, cfg)
        print(("APPLIED: " if written else "NOT APPLIED: ") + msg)
        if written:
            print("The bot validates and applies the overlay at its next start "
                  "(Telegram alert will confirm).")
    elif winner:
        print("Dry run — overlay NOT written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
