"""
Strategy validation CLI (SCRUM-85..91). Runs the 5-stage pipeline for one
strategy and prints the scorecard. Requires a valid Kite session.

  Stage 1  long in-sample backtest (trade-count adequacy)
  Stage 2  anchored walk-forward -> out-of-sample result (the number to trust)
  Stage 3  robustness: parameter plateau, cost/slippage stress, drop-best,
           sub-period consistency, Monte Carlo
  (Stages 4-5 — paper then small-live — are run separately once this passes.)

Usage:
  python validate.py --strategy momentum_vwap_breakout --days 90 \
      --param rsi_entry_threshold=55,60,65 --param target_pct=1.5,2.0
"""
import argparse
import os
import sys

import yaml
from dotenv import load_dotenv

from src.auth import load_kite_session
from src.backtester import Backtester
from src.candle_cache import CandleCache
from src.data_fetcher import DataFetcher
from src.logger import get_logger, setup_logging
from src.param_sweep import expand_grid, run_sweep
from src import validation as V

logger = get_logger("validate")


def _parse_value(v: str):
    for cast in (int, float):
        try:
            return cast(v)
        except ValueError:
            continue
    return v


def main() -> None:
    ap = argparse.ArgumentParser(description="Validate a strategy through the 5-stage pipeline")
    ap.add_argument("--strategy", default=None, help="strategy name (default: config value)")
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--symbols", type=str, default="")
    ap.add_argument("--window", type=int, default=60)
    ap.add_argument("--folds", type=int, default=4)
    ap.add_argument("--param", action="append", default=[], help="name=v1,v2,v3 (repeatable)")
    args = ap.parse_args()

    load_dotenv(dotenv_path=os.path.join("config", ".env"))
    with open(os.path.join("config", "config.yaml")) as f:
        cfg = yaml.safe_load(f)
    setup_logging(level=cfg["logging"]["level"], retention_days=cfg["logging"]["retention_days"])
    if args.strategy:
        cfg["strategy"]["name"] = args.strategy
    strat = cfg["strategy"]["name"]

    param_specs = {}
    for spec in args.param:
        name, _, values = spec.partition("=")
        if values:
            param_specs[name.strip()] = [_parse_value(v.strip()) for v in values.split(",")]
    grid = expand_grid(param_specs)

    symbols = ([s.strip().upper() for s in args.symbols.split(",") if s.strip()]
               or cfg["trading"]["watchlist"])
    regime_on = cfg["strategy"].get("regime_filter_enabled")
    index_symbol = cfg["strategy"].get("regime_index_symbol", "NIFTY 50")

    kite = load_kite_session()
    fetcher = DataFetcher(kite, cfg)
    if not fetcher.load_instruments(symbols + ([index_symbol] if regime_on else [])):
        print("ERROR: instrument load failed"); sys.exit(1)

    cache = CandleCache()
    interval = cfg["trading"]["timeframe"]
    fetch = lambda s: cache.get_or_fetch(s, interval, args.days,
                                         lambda: fetcher.get_candles(s, lookback_days=args.days))
    print(f"Validating '{strat}' over {args.days}d, {len(symbols)} symbols, {len(grid)} param combos...")
    candles = {s: fetch(s) for s in symbols}
    candles = {s: df for s, df in candles.items() if df is not None and not df.empty}
    index_candles = fetch(index_symbol) if regime_on else None
    if not candles:
        print("ERROR: no candle data"); sys.exit(1)

    # Stage 1 — long in-sample
    stage1 = Backtester(cfg, window=args.window).run(candles, index_candles=index_candles)
    print(f"\nStage 1 (in-sample): {stage1.total_trades} trades, net Rs.{stage1.net_pnl}, PF {stage1.profit_factor}")
    if stage1.total_trades < 100:
        print(f"  WARNING: only {stage1.total_trades} trades — below the 100 needed for significance.")

    # full-data sweep (for plateau + chosen params)
    ranked = run_sweep(cfg, candles, grid, index_candles=index_candles, window=args.window) if len(grid) > 1 else []
    chosen = ranked[0]["params"] if ranked else {}

    # Stage 2 — walk-forward OOS
    print("\nStage 2 (walk-forward)...")
    wf = V.walk_forward_rolling(cfg, candles, grid or [{}], folds=args.folds,
                                index_candles=index_candles, window=args.window)
    oos = wf["oos_result"]
    print(f"  In-sample avg net Rs.{wf['in_sample_net_avg']} -> OOS net Rs.{wf['oos_net']} "
          f"({oos.total_trades} OOS trades)"
          + (f", degradation {wf['degradation_pct']}%" if wf["degradation_pct"] is not None else ""))

    # Stage 3 — robustness (on the OOS trades)
    print("\nStage 3 (robustness)...")
    monte = V.monte_carlo(oos.trades)
    drop = V.drop_best_trades(oos.trades)
    sub = V.sub_period_consistency(oos.trades)
    plateau = V.parameter_plateau(ranked, chosen) if ranked else None
    stress = V.cost_slippage_stress(cfg, candles, params=chosen,
                                    index_candles=index_candles, window=args.window)

    report = V.scorecard(oos, monte=monte, sub=sub, plateau=plateau, stress=stress, drop=drop)
    print("\n" + V.format_scorecard(report, title=strat))
    print(f"Monte Carlo: 5th-pct net Rs.{monte['p5_net']} | 95th-pct max DD Rs.{monte['p95_max_drawdown']}")
    print(f"Drop top {drop['dropped']} winners: net Rs.{drop['net_full']} -> Rs.{drop['net_after_drop']}")
    print(f"Sub-period nets: {sub['net_by_period']} ({sub['profitable_periods']}/3 profitable)")
    print(f"Cost/slippage stress: PF {stress['profit_factor']} ({'survives' if stress['survives'] else 'dies'})")


if __name__ == "__main__":
    main()
