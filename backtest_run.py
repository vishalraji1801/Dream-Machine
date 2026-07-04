"""
Streamlined multi-timeframe backtest pipeline (SCRUM-92).

One command:
  1. select stocks with the universe builder
  2. pull a year of 1/5/15/30/60-min candles into the backtest DB (skip if fetched today)
  3. run the strategy across every timeframe
  4. hand the summary to the headless Claude analyst (subscription-only)

Requires a valid Kite session (run auth.py first).

Usage:
  python backtest_run.py                       # default: config num_stocks, analyze
  python backtest_run.py --num-stocks 20
  python backtest_run.py --rebuild             # clear + refetch all data
  python backtest_run.py --no-analyze          # skip the Claude step
"""
import argparse
import os
import subprocess
import sys

import yaml
from dotenv import load_dotenv

from src.auth import load_kite_session
from src.backtest_runner import (format_summary, load_all, run_across_timeframes,
                                 write_summary)
from src.backtest_store import BacktestStore
from src.data_fetcher import DataFetcher
from src.historical_loader import HistoricalLoader
from src.logger import get_logger, setup_logging
from src.stock_selector import select_stocks

logger = get_logger("backtest_run")


def main() -> None:
    ap = argparse.ArgumentParser(description="Streamlined multi-timeframe backtest pipeline")
    ap.add_argument("--num-stocks", type=int, default=None)
    ap.add_argument("--strategy", default=None)
    ap.add_argument("--window", type=int, default=60)
    ap.add_argument("--rebuild", action="store_true", help="clear the store and refetch")
    ap.add_argument("--no-analyze", action="store_true", help="skip the Claude analyst step")
    args = ap.parse_args()

    load_dotenv(dotenv_path=os.path.join("config", ".env"))
    with open(os.path.join("config", "config.yaml")) as f:
        cfg = yaml.safe_load(f)
    setup_logging(level=cfg["logging"]["level"], retention_days=cfg["logging"]["retention_days"])
    if args.strategy:
        cfg["strategy"]["name"] = args.strategy
    strategy = cfg["strategy"]["name"]
    num_stocks = args.num_stocks or cfg["backtest_data"].get("num_stocks", 30)

    kite = load_kite_session()
    store = BacktestStore(cfg["backtest_data"].get("store_path", os.path.join("data_cache", "backtest_data.db")))
    if args.rebuild:
        store.clear()
    loader = HistoricalLoader(kite, store, cfg)

    # 1. select stocks
    stocks = select_stocks(kite, cfg, num_stocks)
    if not stocks:
        print("ERROR: no stocks selected (check universe filters)"); sys.exit(1)

    # index for the regime filter
    index = None
    index_symbol = cfg["strategy"].get("regime_index_symbol", "NIFTY 50")
    if cfg["strategy"].get("regime_filter_enabled"):
        fetcher = DataFetcher(kite, cfg)
        fetcher.load_instruments([index_symbol])
        tok = fetcher._instruments.get(index_symbol)
        if tok:
            index = {"symbol": index_symbol, "token": tok}

    # 2. load a year of every timeframe
    tfs = ", ".join(tf["label"] for tf in loader.timeframes)
    print(f"Loading {cfg['backtest_data'].get('lookback_days', 365)}d of [{tfs}] for "
          f"{len(stocks)} stocks (+index)... this can take a while on first run.")
    load_all(loader, stocks, index, force=args.rebuild)

    # 3. run across timeframes
    print(f"Running '{strategy}' across all timeframes...")
    summaries = run_across_timeframes(
        cfg, store, [s["symbol"] for s in stocks],
        index_symbol=index_symbol if index else None, window=args.window)
    path = write_summary(summaries, strategy)
    print("\n" + format_summary(summaries, strategy))
    print(f"\nSummary written: {path}")

    # 4. hand to the headless Claude analyst
    if not args.no_analyze:
        print("\nInvoking Claude backtest analyst (subscription-only)...")
        rc = subprocess.run([sys.executable, "run_ai_agent.py", "backtest"],
                            cwd=os.path.dirname(os.path.abspath(__file__)))
        if rc.returncode != 0:
            print("Claude analysis step did not complete (is `claude` installed and logged in?).")


if __name__ == "__main__":
    main()
