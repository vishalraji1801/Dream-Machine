"""
Go-live readiness evaluation (V2 P7).

Reads the paper-trading evidence from the SQLite ledger and checks it against
objective criteria. This is a decision AID for a human — it NEVER flips
paper_trading.enabled. Going live remains an explicit, manual step.
"""
from typing import Optional

_DEFAULT_CRITERIA = {
    "min_trading_days": 5,
    "min_trades": 20,
    "min_net_pnl": 0.0,
    "min_profit_factor": 1.2,
    "min_win_rate": 45.0,
}


def evaluate_readiness(trades: list[dict], criteria: Optional[dict] = None) -> dict:
    """
    trades: paper trades (dicts with pnl, entry_time). Returns a report with each
    criterion's pass/fail and an overall `ready` boolean.
    """
    c = {**_DEFAULT_CRITERIA, **(criteria or {})}
    n = len(trades)
    net = round(sum(t["pnl"] for t in trades), 2)
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))
    pf = (gross_profit / gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)
    win_rate = round(100 * len(wins) / n, 2) if n else 0.0
    days = len({str(t.get("entry_time", ""))[:10] for t in trades if t.get("entry_time")})

    checks = {
        "trading_days":  (days >= c["min_trading_days"], days, c["min_trading_days"]),
        "trade_count":   (n >= c["min_trades"], n, c["min_trades"]),
        "net_pnl":       (net > c["min_net_pnl"], net, c["min_net_pnl"]),
        "profit_factor": (pf >= c["min_profit_factor"], round(pf, 2) if pf != float("inf") else pf, c["min_profit_factor"]),
        "win_rate":      (win_rate >= c["min_win_rate"], win_rate, c["min_win_rate"]),
    }
    return {
        "ready": all(passed for passed, *_ in checks.values()),
        "checks": checks,
        "summary": {"trades": n, "net_pnl": net, "win_rate": win_rate,
                    "profit_factor": round(pf, 2) if pf != float("inf") else pf,
                    "trading_days": days},
    }


def format_report(report: dict) -> str:
    lines = ["=" * 60, " GO-LIVE READINESS (paper evidence)", "=" * 60]
    for name, (passed, actual, need) in report["checks"].items():
        mark = "PASS" if passed else "FAIL"
        lines.append(f" [{mark}] {name:<14} actual={actual}  required>={need}")
    lines.append("-" * 60)
    verdict = "READY (human sign-off still required)" if report["ready"] else "NOT READY"
    lines.append(f" Verdict: {verdict}")
    lines.append(" This tool never flips paper_trading.enabled. Going live is manual.")
    lines.append("=" * 60)
    return "\n".join(lines)
