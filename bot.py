"""
Unified bot CLI (SCRUM-102) — one entry point for the whole lifecycle.

    python bot.py auth                    daily Kite login (TOTP only)
    python bot.py run                     start the trading bot (paper or live per config)
    python bot.py backtest [...]          multi-strategy multi-TF backtest (backtest_run.py args)
    python bot.py validate [...]          5-stage validation pipeline (validate.py args)
    python bot.py sweep [...]             parameter sweep (sweep.py args)
    python bot.py status                  mode, token, market, paper progress vs go-live gate
    python bot.py golive --confirm        flip to LIVE (readiness gate enforced; --force overrides)
    python bot.py gopaper                 flip back to paper instantly

The gate never flips anything on its own: going live always requires this
command with an explicit --confirm from you.
"""
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))

_PASSTHROUGH = {
    "auth": "auth.py",
    "run": "main.py",
    "backtest": "backtest_run.py",
    "validate": "validate.py",
    "sweep": "sweep.py",
    "tune": "autotune.py",
    "make": "make.py",
}


def _delegate(script: str, extra: list) -> int:
    """Run a sibling script with inherited stdio (TOTP prompts work) and
    propagate its exit code (the start_bot.bat watchdog depends on it)."""
    cmd = [sys.executable, os.path.join(ROOT, script)] + extra
    return subprocess.call(cmd, cwd=ROOT)


def cmd_status(_args) -> int:
    from src.ops import format_status, gather_status
    print(format_status(gather_status()))
    return 0


def cmd_golive(args) -> int:
    import yaml
    from src.go_live import format_report
    from src.ops import get_trading_mode, golive_decision, set_trading_mode
    from src.trade_db import TradeDB

    if get_trading_mode() == "live":
        print("Already in LIVE mode.")
        return 0

    with open(os.path.join("config", "config.yaml")) as f:
        cfg = yaml.safe_load(f)
    paper = TradeDB().trades(source="paper")
    decision = golive_decision(paper, cfg.get("go_live", {}), force=args.force)
    print(format_report(decision))

    if not decision["allowed"]:
        print("\nGate FAILED — not switching. Accumulate more paper evidence, or use "
              "--force only if you accept the risk knowingly.")
        return 1
    if not args.confirm:
        print("\nGate result above. To actually switch to LIVE, re-run with --confirm:")
        print("  python bot.py golive --confirm" + (" --force" if args.force else ""))
        return 1
    if decision["forced"]:
        print("\n!! Going live with a FAILED gate (--force). You own this decision. !!")

    set_trading_mode(live=True)
    print("\nMode switched to LIVE. Real orders will be placed on the next run.")
    print("Start at reduced capital (risk.total_capital) and watch Telegram closely.")
    print("Revert anytime: python bot.py gopaper")
    return 0


def cmd_gopaper(_args) -> int:
    from src.ops import get_trading_mode, set_trading_mode
    if get_trading_mode() == "paper":
        print("Already in PAPER mode.")
        return 0
    set_trading_mode(live=False)
    print("Mode switched back to PAPER. No real orders will be placed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="bot", description="Trading Bot — unified lifecycle CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    for name in _PASSTHROUGH:
        p = sub.add_parser(name, add_help=False)
        p.add_argument("extra", nargs=argparse.REMAINDER)

    sub.add_parser("status")
    p_live = sub.add_parser("golive")
    p_live.add_argument("--confirm", action="store_true",
                        help="actually flip to live (otherwise dry-run report only)")
    p_live.add_argument("--force", action="store_true",
                        help="override a failed readiness gate (dangerous)")
    sub.add_parser("gopaper")

    args = parser.parse_args()
    if args.command in _PASSTHROUGH:
        return _delegate(_PASSTHROUGH[args.command], args.extra)
    if args.command == "status":
        return cmd_status(args)
    if args.command == "golive":
        return cmd_golive(args)
    if args.command == "gopaper":
        return cmd_gopaper(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
