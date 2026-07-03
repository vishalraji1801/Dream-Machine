"""
Parameter sweep CLI — find which strategy parameters held up historically.
Requires a valid Kite session (run auth.py first).

Usage:
    python sweep.py --days 15 --param rsi_entry_threshold=55,60,65 --param volume_multiplier=1.2,1.5,2.0
    python sweep.py --days 10 --symbols RELIANCE,TCS --param regime_band_pct=0.05,0.1,0.2
"""
import argparse
import os
import sys

import yaml
from dotenv import load_dotenv

from src.auth import load_kite_session
from src.data_fetcher import DataFetcher
from src.logger import get_logger, setup_logging
from src.param_sweep import expand_grid, format_sweep_report, run_sweep

logger = get_logger("sweep")


def _parse_value(v: str):
    try:
        return int(v)
    except ValueError:
        try:
            return float(v)
        except ValueError:
            return v


def main() -> None:
    parser = argparse.ArgumentParser(description="Grid-search strategy parameters over the backtester")
    parser.add_argument("--days", type=int, default=15)
    parser.add_argument("--symbols", type=str, default="",
                        help="Comma-separated subset of the watchlist")
    parser.add_argument("--window", type=int, default=60)
    parser.add_argument("--param", action="append", default=[],
                        help="name=v1,v2,v3 — repeatable, one per parameter")
    args = parser.parse_args()

    if not args.param:
        print("ERROR: at least one --param name=v1,v2 is required")
        sys.exit(1)

    param_specs = {}
    for spec in args.param:
        name, _, values = spec.partition("=")
        if not values:
            print(f"ERROR: bad --param format: {spec}")
            sys.exit(1)
        param_specs[name.strip()] = [_parse_value(v.strip()) for v in values.split(",")]

    grid = expand_grid(param_specs)
    print(f"Sweeping {len(grid)} parameter combinations...")

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
    if not fetcher.load_instruments(symbols + ([index_symbol] if regime_on else [])):
        print("ERROR: could not load instrument tokens")
        sys.exit(1)

    print(f"Fetching {args.days}d of candles for {len(symbols)} symbols...")
    candles = {}
    for sym in symbols:
        df = fetcher.get_candles(sym, lookback_days=args.days)
        if df is not None and not df.empty:
            candles[sym] = df

    if not candles:
        print("ERROR: no candle data fetched")
        sys.exit(1)

    index_candles = fetcher.get_candles(index_symbol, lookback_days=args.days) if regime_on else None

    results = run_sweep(cfg, candles, grid, index_candles=index_candles, window=args.window)
    print(format_sweep_report(results))


if __name__ == "__main__":
    main()
