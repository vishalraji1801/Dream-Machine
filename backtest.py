"""
Backtest CLI — validate the strategy on historical Kite data.
Requires a valid Kite session (run auth.py first).

Usage:
    python backtest.py --days 10
    python backtest.py --days 30 --symbols RELIANCE,TCS,INFY
"""
import argparse
import os
import sys

import yaml
from dotenv import load_dotenv

from src.auth import load_kite_session
from src.backtester import Backtester, format_report
from src.candle_cache import CandleCache
from src.data_fetcher import DataFetcher
from src.logger import get_logger, setup_logging

logger = get_logger("backtest")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest the trading strategy on historical data")
    parser.add_argument("--days", type=int, default=10,
                        help="Lookback days of 5-min candles (max ~60 for Kite)")
    parser.add_argument("--symbols", type=str, default="",
                        help="Comma-separated subset of the watchlist (default: full watchlist)")
    parser.add_argument("--window", type=int, default=60,
                        help="Rolling candle window passed to the strategy per evaluation")
    parser.add_argument("--no-cache", action="store_true",
                        help="Bypass the on-disk candle cache")
    args = parser.parse_args()

    load_dotenv(dotenv_path=os.path.join("config", ".env"))
    with open(os.path.join("config", "config.yaml")) as f:
        cfg = yaml.safe_load(f)
    setup_logging(level=cfg["logging"]["level"],
                  retention_days=cfg["logging"]["retention_days"])

    symbols = ([s.strip().upper() for s in args.symbols.split(",") if s.strip()]
               or cfg["trading"]["watchlist"])

    regime_on = cfg["strategy"].get("regime_filter_enabled")
    index_symbol = cfg["strategy"].get("regime_index_symbol", "NIFTY 50")

    kite = load_kite_session()
    fetcher = DataFetcher(kite, cfg)
    load_list = symbols + ([index_symbol] if regime_on else [])
    if not fetcher.load_instruments(load_list):
        print("ERROR: could not load instrument tokens")
        sys.exit(1)

    cache = CandleCache()
    interval = cfg["trading"]["timeframe"]

    def _fetch(sym):
        if args.no_cache:
            return fetcher.get_candles(sym, lookback_days=args.days)
        return cache.get_or_fetch(sym, interval, args.days,
                                  lambda: fetcher.get_candles(sym, lookback_days=args.days))

    print(f"Fetching {args.days}d of 5-min candles for {len(symbols)} symbols...")
    candles = {}
    for sym in symbols:
        df = _fetch(sym)
        if df is not None and not df.empty:
            candles[sym] = df
        else:
            print(f"  WARNING: no data for {sym} — skipping")

    if not candles:
        print("ERROR: no candle data fetched")
        sys.exit(1)

    index_candles = None
    if regime_on:
        index_candles = _fetch(index_symbol)
        if index_candles is None:
            print(f"  WARNING: no index data for {index_symbol} — regime filter off")

    print(f"Running backtest over {sum(len(d) for d in candles.values())} candles...")
    result = Backtester(cfg, window=args.window).run(candles, index_candles=index_candles)
    print(format_report(result))


if __name__ == "__main__":
    main()
