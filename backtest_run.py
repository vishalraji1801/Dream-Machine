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
from src.backtest_runner import format_matrix, load_all, run_strategies, write_matrix
from src.backtest_store import BacktestStore
from src.data_fetcher import DataFetcher
from src.historical_loader import HistoricalLoader
from src.logger import get_logger, setup_logging
from src.stock_selector import select_stocks
from src.strategy import STRATEGY_REGISTRY

logger = get_logger("backtest_run")


def main() -> None:
    ap = argparse.ArgumentParser(description="Streamlined multi-timeframe backtest pipeline")
    ap.add_argument("--num-stocks", type=int, default=None)
    ap.add_argument("--strategy", default=None, help="single strategy (shorthand)")
    ap.add_argument("--strategies", default="",
                    help="comma list of strategies to compare (default: all registered)")
    ap.add_argument("--window", type=int, default=60)
    ap.add_argument("--symbols", default="", help="comma list to restrict to")
    ap.add_argument("--offline", action="store_true",
                    help="skip Kite: backtest symbols already in the store (no network/auth)")
    ap.add_argument("--rebuild", action="store_true", help="clear the store and refetch")
    ap.add_argument("--no-analyze", action="store_true", help="skip the Claude analyst step")
    args = ap.parse_args()

    load_dotenv(dotenv_path=os.path.join("config", ".env"))
    with open(os.path.join("config", "config.yaml")) as f:
        cfg = yaml.safe_load(f)
    setup_logging(level=cfg["logging"]["level"], retention_days=cfg["logging"]["retention_days"])
    if args.strategies:
        strategies = [s.strip() for s in args.strategies.split(",") if s.strip()]
    elif args.strategy:
        strategies = [args.strategy]
    else:
        strategies = list(STRATEGY_REGISTRY.keys())
    strategies = [s for s in strategies if s in STRATEGY_REGISTRY]
    if not strategies:
        print("ERROR: no valid strategies. Known:", ", ".join(STRATEGY_REGISTRY)); sys.exit(1)
    num_stocks = args.num_stocks or cfg["backtest_data"].get("num_stocks", 30)
    req_symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    index_symbol = cfg["strategy"].get("regime_index_symbol", "NIFTY 50")
    store = BacktestStore(cfg["backtest_data"].get("store_path", os.path.join("data_cache", "backtest_data.db")))

    # ── Offline: backtest what's already in the store, no Kite/auth ──────────────
    if args.offline:
        symbols = req_symbols or [s for s in store.symbols() if s != index_symbol]
        if not symbols:
            print("No symbols in the store. Run a normal fetch first."); sys.exit(1)
        has_index = store.candle_count(index_symbol, "5min") > 0
        print(f"Offline backtest of [{', '.join(strategies)}] on {len(symbols)} stored "
              f"symbol(s): {symbols[:10]}" + ("..." if len(symbols) > 10 else ""))
        rows = run_strategies(cfg, store, symbols, strategies,
                              index_symbol=index_symbol if has_index else None, window=args.window)
        path = write_matrix(rows)
        print("\n" + format_matrix(rows) + f"\n\nMatrix written: {path}")
        _maybe_analyze(args)
        return

    kite = load_kite_session()
    if args.rebuild:
        store.clear()
    loader = HistoricalLoader(kite, store, cfg)

    # 1. select stocks
    stocks = select_stocks(kite, cfg, num_stocks)
    if req_symbols:
        stocks = [s for s in stocks if s["symbol"] in req_symbols]
    if not stocks:
        print("ERROR: no stocks selected (check universe filters / --symbols)"); sys.exit(1)

    # index for the regime filter
    index = None
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

    # 3. run every strategy across every timeframe
    print(f"Running [{', '.join(strategies)}] across all timeframes...")
    rows = run_strategies(
        cfg, store, [s["symbol"] for s in stocks], strategies,
        index_symbol=index_symbol if index else None, window=args.window)
    path = write_matrix(rows)
    print("\n" + format_matrix(rows))
    print(f"\nMatrix written: {path}")

    # 4. hand to the headless Claude analyst
    _maybe_analyze(args)


def _maybe_analyze(args) -> None:
    """Invoke the headless Claude backtest analyst (subscription-only) unless skipped."""
    if args.no_analyze:
        return
    print("\nInvoking Claude backtest analyst (subscription-only)...")
    rc = subprocess.run([sys.executable, "run_ai_agent.py", "backtest"],
                        cwd=os.path.dirname(os.path.abspath(__file__)))
    if rc.returncode != 0:
        print("Claude analysis step did not complete (is `claude` installed and logged in?).")


if __name__ == "__main__":
    main()
