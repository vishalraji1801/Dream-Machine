"""
Operational helpers for the unified bot CLI (SCRUM-102).

- get/set trading mode: flips paper_trading.enabled in config.yaml with a
  targeted line edit so comments and formatting are preserved.
- go-live decision: wraps the paper-evidence readiness gate (SCRUM-83); the
  flip to live always requires an explicit human --confirm on top of the gate.
- status: one snapshot of mode, token freshness, market state, and paper
  progress against the gate.
"""
import os
import re
from datetime import datetime
from typing import Optional

import yaml

from src.go_live import evaluate_readiness
from src.logger import get_logger

logger = get_logger("ops")

_ENABLED_RE = re.compile(r"^(\s+enabled:\s*)(true|false)(.*)$")


def get_trading_mode(config_path: str = os.path.join("config", "config.yaml")) -> str:
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    return "paper" if cfg.get("paper_trading", {}).get("enabled", True) else "live"


def set_trading_mode(live: bool,
                     config_path: str = os.path.join("config", "config.yaml")) -> str:
    """
    Flip paper_trading.enabled with a line-level edit (comments preserved).
    Returns the new mode string. Raises if the key can't be located.
    """
    with open(config_path, encoding="utf-8") as f:
        lines = f.readlines()

    in_block = False
    changed = False
    for i, line in enumerate(lines):
        if re.match(r"^paper_trading:", line):
            in_block = True
            continue
        if in_block:
            if line.strip() and not line.startswith((" ", "\t")):
                break  # left the paper_trading block
            m = _ENABLED_RE.match(line.rstrip("\n"))
            if m:
                value = "false" if live else "true"
                lines[i] = f"{m.group(1)}{value}{m.group(3)}\n"
                changed = True
                break
    if not changed:
        raise ValueError("paper_trading.enabled not found in config — cannot switch mode")

    with open(config_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    mode = "live" if live else "paper"
    logger.warning(f"Trading mode set to {mode.upper()}")
    return mode


def golive_decision(paper_trades: list, criteria: Optional[dict] = None,
                    force: bool = False) -> dict:
    """Evaluate the gate. 'allowed' means the flip may proceed (gate pass or forced)."""
    report = evaluate_readiness(paper_trades, criteria)
    report["forced"] = bool(force and not report["ready"])
    report["allowed"] = report["ready"] or force
    return report


def gather_status(config_path: str = os.path.join("config", "config.yaml")) -> dict:
    """Snapshot for `bot status`. Every field degrades gracefully if unavailable."""
    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    status: dict = {"mode": get_trading_mode(config_path)}

    token_path = os.getenv("KITE_ACCESS_TOKEN_PATH", "./token.txt")
    if os.path.exists(token_path):
        mtime = datetime.fromtimestamp(os.path.getmtime(token_path))
        status["token_fresh_today"] = mtime.date() == datetime.now().date()
        status["token_time"] = mtime.strftime("%Y-%m-%d %H:%M")
    else:
        status["token_fresh_today"] = False
        status["token_time"] = None

    try:
        from src.market_calendar import MarketCalendar
        status["market"] = MarketCalendar(cfg).status_text()
    except Exception:
        status["market"] = "unknown"

    try:
        from src.trade_db import TradeDB
        db = TradeDB()
        paper = db.trades(source="paper")
        status["paper_trades"] = len(paper)
        status["paper_net_pnl"] = round(sum(t["pnl"] for t in paper), 2)
        gate = evaluate_readiness(paper, cfg.get("go_live", {}))
        status["gate_ready"] = gate["ready"]
        status["gate_checks"] = {k: v[0] for k, v in gate["checks"].items()}
    except Exception:
        status["paper_trades"] = 0
        status["paper_net_pnl"] = 0.0
        status["gate_ready"] = False
        status["gate_checks"] = {}

    matrices = sorted(
        (p for p in os.listdir("logs") if p.startswith("backtest_matrix")),
        reverse=True) if os.path.isdir("logs") else []
    status["latest_backtest"] = os.path.join("logs", matrices[0]) if matrices else None
    return status


def format_status(status: dict) -> str:
    mode = status["mode"].upper()
    lines = [
        "=" * 56,
        f" TRADING BOT STATUS — mode: {mode}",
        "=" * 56,
        f" Market         : {status['market']}",
        f" Kite token     : {'fresh (today)' if status['token_fresh_today'] else 'STALE — run: bot auth'}"
        + (f"  [{status['token_time']}]" if status.get("token_time") else ""),
        f" Paper trades   : {status['paper_trades']} (net Rs.{status['paper_net_pnl']})",
        f" Go-live gate   : {'READY' if status['gate_ready'] else 'not yet'}",
    ]
    for name, passed in status.get("gate_checks", {}).items():
        lines.append(f"   [{'PASS' if passed else 'FAIL'}] {name}")
    if status.get("latest_backtest"):
        lines.append(f" Latest backtest: {status['latest_backtest']}")
    lines.append("=" * 56)
    if mode == "LIVE":
        lines.append(" !! REAL ORDERS ARE ENABLED. 'bot gopaper' reverts. !!")
    return "\n".join(lines)


def shadow_report(state_path: str = os.path.join("logs", "swing_state.json"),
                  db_path: str = os.path.join("logs", "trades.db"), kite=None) -> str:
    """The swing sleeve's SHADOW book — every signal (incl. the ones Rs.5000 refused) tracked
    unconstrained. Shows REALIZED shadow P&L per strategy (closed shadow trades) + OPEN shadow
    positions marked-to-market (if a Kite session is passed). Answers 'would the trades I
    couldn't fund have won or lost?'."""
    import json
    import sqlite3

    realized: dict = {}
    if os.path.exists(db_path):
        con = sqlite3.connect(db_path); con.row_factory = sqlite3.Row
        for r in con.execute("SELECT strategy, pnl FROM trades WHERE source='shadow'"):
            d = realized.setdefault(r["strategy"], {"n": 0, "net": 0.0, "wins": 0})
            pnl = r["pnl"] or 0.0
            d["n"] += 1; d["net"] += pnl; d["wins"] += 1 if pnl > 0 else 0
        con.close()

    open_pos = []
    if os.path.exists(state_path):
        try:
            open_pos = list(json.load(open(state_path, encoding="utf-8")).get("shadow", {}).values())
        except Exception:
            pass
    ltp: dict = {}
    if kite is not None and open_pos:
        try:
            syms = sorted({p["symbol"] for p in open_pos})
            ltp = {k.split(":")[1]: v["last_price"]
                   for k, v in kite.ltp(["NSE:" + s for s in syms]).items()}
        except Exception:
            ltp = {}
    unreal: dict = {}
    for p in open_pos:
        cur = ltp.get(p["symbol"])
        u = (((cur - p["entry_price"]) if p["direction"] == "BUY" else (p["entry_price"] - cur))
             * p["quantity"]) if cur else None
        d = unreal.setdefault(p["strategy"], {"n": 0, "upnl": 0.0, "marked": 0})
        d["n"] += 1
        if u is not None:
            d["upnl"] += u; d["marked"] += 1

    strategies = sorted(set(realized) | set(unreal),
                        key=lambda s: realized.get(s, {}).get("net", 0), reverse=True)
    L = ["=" * 78,
         " SWING SHADOW BOOK — every signal tracked unconstrained (source='shadow')",
         "=" * 78,
         f" {'strategy':16} {'closed':>6} {'realized':>10} {'win%':>5} {'open':>5} {'unrealized':>11}",
         " " + "-" * 74]
    tot = {"n": 0, "net": 0.0, "wins": 0, "open": 0, "upnl": 0.0}
    for s in strategies:
        rz = realized.get(s, {"n": 0, "net": 0.0, "wins": 0})
        uz = unreal.get(s, {"n": 0, "upnl": 0.0, "marked": 0})
        win = f"{100 * rz['wins'] // rz['n']}" if rz["n"] else "-"
        umark = f"Rs.{uz['upnl']:>+8,.0f}" if uz["marked"] else (f"{uz['n']} open" if uz["n"] else "-")
        L.append(f" {s:16} {rz['n']:>6} {rz['net']:>+10,.0f} {win:>5} {uz['n']:>5} {umark:>11}")
        tot["n"] += rz["n"]; tot["net"] += rz["net"]; tot["wins"] += rz["wins"]
        tot["open"] += uz["n"]; tot["upnl"] += uz["upnl"]
    L.append(" " + "-" * 74)
    twin = f"{100 * tot['wins'] // tot['n']}" if tot["n"] else "-"
    L.append(f" {'TOTAL':16} {tot['n']:>6} {tot['net']:>+10,.0f} {twin:>5} {tot['open']:>5} "
             f"Rs.{tot['upnl']:>+8,.0f}")
    L.append("=" * 78)
    if not tot["n"] and not tot["open"]:
        L.append(" (no shadow trades yet — runs accumulate from the next `bot.py run`)")
    if kite is None and tot["open"]:
        L.append(" (open positions not marked-to-market — no Kite session; run with a fresh token)")
    return "\n".join(L)
