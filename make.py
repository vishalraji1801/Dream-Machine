#!/usr/bin/env python
"""bot.py make ... — Strategy Maker CLI (spec section 9).

    bot.py make status                         funnel counts, N_effective, current bar
    bot.py make generate --max-trials N --seed S --symbols K [--workers W]
                                               run the full funnel on the daily store
                                               (--workers >1 = process-parallel, identical)
    bot.py make screen|gauntlet|reserve        (run as part of 'generate' in this build)
"""
import argparse
import os
import sys

import yaml

ROOT = os.path.dirname(os.path.abspath(__file__))


def _registry():
    from maker.registry import Registry
    return Registry(os.path.join(ROOT, "data_cache", "maker_trials.db"))


def cmd_status(_args) -> int:
    from maker.bar import pf_required
    from maker.reserve import effective_reserve_table
    reg = _registry()
    n = reg.n_effective()
    print(f"N_effective (distinct families at screen+): {n}")
    print(f"current pf_required:                        {pf_required(max(n, 10))}")
    print("stage counts:")
    for stage in ("GEN_REJECT", "SCREEN", "GAUNTLET", "RESERVE", "PAPER"):
        print(f"  {stage:11} {reg.count(stage=stage)}")
    # Effective reserve verdicts honour VOID supersessions (append-only corrections),
    # so a bug's invalidated DEAD no longer counts and a re-tested family shows its real
    # status. This is the authoritative ALIVE count, not the raw ALIVE row count.
    verdicts = effective_reserve_table(reg.rows())
    alive = sorted(f for f, s in verdicts.items() if s == "ALIVE")
    print(f"  {'ALIVE':11} {len(alive)}" + (f"  {alive}" if alive else ""))
    return 0


INTRADAY_TIMEFRAMES = ["1min", "5min", "15min", "30min", "1hr"]


def _timeframes(args, intraday) -> list:
    if not intraday:
        return ["day"]
    if args.timeframe in ("day", "all"):
        return list(INTRADAY_TIMEFRAMES)
    return [t.strip() for t in args.timeframe.split(",")]        # single or comma-list


def _run_one_tf(args, store, lock, tf, intraday) -> dict:
    """One full generate->screen->gauntlet->reserve campaign on a single timeframe."""
    cfg = yaml.safe_load(open(os.path.join(ROOT, "config", "config.yaml")))
    cfg["strategy"]["regime_filter_enabled"] = False
    if intraday:
        # keep the session entry window + square-off (backtester needs them for MIS); costs
        # switch to intraday and the per-candidate screen adds execution slippage.
        cfg["costs"]["product"] = "intraday"
        product, min_bars = "intraday", 2000
    else:
        cfg["trading"]["entry_start_time"] = ""; cfg["trading"]["entry_end_time"] = ""
        cfg["costs"]["product"] = "delivery"
        product, min_bars = "delivery", 1000
    syms = [s for s in store.symbols() if store.candle_count(s, tf) > min_bars][:args.symbols]
    if lock is not None:
        syms = [s for s in syms if s in set(lock["symbols"])]
    if not syms:
        print(f"[{tf}] no history >{min_bars} bars in the store — skipped.")
        return {}
    candles = {s: store.get_candles(s, tf) for s in syms}
    tf_stamp = tf if intraday else None      # stamp intraday candidates with their timeframe
    print(f"Campaign [{args.sleeve}/{tf}]: {args.max_trials} candidates, seed {args.seed}, "
          f"{len(syms)} symbols, workers {args.workers}, reserve {'ON' if lock else 'off'}...")
    if args.workers > 1:                      # process-parallel; byte-identical to serial
        from maker.parallel_campaign import run_campaign_parallel
        return run_campaign_parallel(args.max_trials, args.seed, candles, cfg, _registry(),
                                     lock=lock, workers=args.workers, product=product,
                                     sleeve=args.sleeve, timeframe=tf_stamp)
    from maker.campaign import run_campaign
    return run_campaign(args.max_trials, args.seed, candles, cfg, _registry(), lock=lock,
                        product=product, sleeve=args.sleeve, timeframe=tf_stamp)


def cmd_generate(args) -> int:
    from src.backtest_store import BacktestStore
    intraday = args.sleeve == "intraday"
    store = BacktestStore(os.path.join(ROOT, "data_cache", "backtest_data.db"))
    lock = None
    lock_path = os.path.join(ROOT, "data_cache", "reserve_lock.json")
    if os.path.exists(lock_path):
        from maker.reserve import load_lock
        lock = load_lock(lock_path)
        print(f"Reserve lock active: cutoff {lock['cutoff_date']}, {len(lock['symbols'])} names.")
    tfs = _timeframes(args, intraday)
    if len(tfs) > 1:
        print(f"Running {len(tfs)} timeframe hunts: {tfs}")
    for tf in tfs:
        counts = _run_one_tf(args, store, lock, tf, intraday)
        print(f"counts [{tf}]:", counts)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="bot.py make")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    g = sub.add_parser("generate")
    g.add_argument("--max-trials", type=int, default=50)
    g.add_argument("--seed", type=int, default=0)
    g.add_argument("--symbols", type=int, default=60)
    g.add_argument("--workers", type=int, default=1,
                   help="process-parallel workers (>1 runs the pool; identical results)")
    g.add_argument("--sleeve", default="swing", choices=["swing", "intraday"],
                   help="swing (daily/CNC, default) or intraday (MIS, session blocks)")
    g.add_argument("--timeframe", default="day",
                   help="candle timeframe (swing: day; intraday: 5min/15min/30min/1hr)")
    for name in ("screen", "gauntlet", "reserve"):
        sub.add_parser(name)
    args = ap.parse_args(argv)
    if args.cmd == "status":
        return cmd_status(args)
    if args.cmd == "generate":
        return cmd_generate(args)
    print(f"'{args.cmd}' runs as part of 'generate' in this build.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
