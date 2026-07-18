#!/usr/bin/env python
"""bot.py make ... — Strategy Maker CLI (spec section 9).

    bot.py make status                         funnel counts, N_effective, current bar
    bot.py make generate --max-trials N --seed S --symbols K
                                               run the full funnel on the daily store
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
    reg = _registry()
    n = reg.n_effective()
    print(f"N_effective (distinct families at screen+): {n}")
    print(f"current pf_required:                        {pf_required(max(n, 10))}")
    print("stage counts:")
    for stage in ("GEN_REJECT", "SCREEN", "GAUNTLET", "RESERVE", "PAPER"):
        print(f"  {stage:11} {reg.count(stage=stage)}")
    print(f"  {'ALIVE':11} {reg.count(status='ALIVE')}")
    return 0


def cmd_generate(args) -> int:
    from maker.campaign import run_campaign
    from src.backtest_store import BacktestStore
    cfg = yaml.safe_load(open(os.path.join(ROOT, "config", "config.yaml")))
    cfg["strategy"]["regime_filter_enabled"] = False
    cfg["trading"]["entry_start_time"] = ""; cfg["trading"]["entry_end_time"] = ""
    cfg["costs"]["product"] = "delivery"
    store = BacktestStore(os.path.join(ROOT, "data_cache", "backtest_data.db"))
    syms = [s for s in store.symbols() if store.candle_count(s, "day") > 1000][:args.symbols]
    if not syms:
        print("No daily history in the store. Fetch the F&O daily universe first.")
        return 1
    candles = {s: store.get_candles(s, "day") for s in syms}
    print(f"Campaign: {args.max_trials} candidates, seed {args.seed}, {len(syms)} symbols...")
    counts = run_campaign(args.max_trials, args.seed, candles, cfg, _registry(), window=160)
    print("counts:", counts)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="bot.py make")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    g = sub.add_parser("generate")
    g.add_argument("--max-trials", type=int, default=50)
    g.add_argument("--seed", type=int, default=0)
    g.add_argument("--symbols", type=int, default=60)
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
