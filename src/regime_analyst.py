"""
Regime→fit analyst (regime router, commit 6).

The learned map: don't hand-assign which strategy suits which regime — measure it
from the ledger. `compute_regime_fit` (pure) buckets closed trades by
(strategy × regime) and computes PF / expectancy / net. Buckets below the sample
floor are marked `insufficient_data` and are NOT trusted as an edge — the router
treats them as neutral, never a guess.

`write_regime_fit` is the I/O side (the weekly researcher job): it merges only the
trusted buckets into each strategy's YAML `regime_fit` block. Ledger PF is
in-sample; the spec requires walk-forward OOS confirmation before a fit is trusted
for live weighting (see docs/specs section 6) — this module supplies the sample
guard; the auto-tuner supplies the OOS gate.
"""
import os
from typing import Optional

import yaml

from src.logger import get_logger

logger = get_logger("regime_analyst")


def compute_regime_fit(trades: list, min_trades: int = 30) -> dict:
    """
    trades: dicts with at least 'strategy', 'regime', 'pnl'.
    Returns {strategy: {regime: {pf, trades, expectancy, net, status}}}.
    status is 'ok' only when trades >= min_trades, else 'insufficient_data'.
    """
    buckets: dict = {}
    for t in trades:
        strat, reg = t.get("strategy"), t.get("regime")
        if not strat or not reg:
            continue
        buckets.setdefault((strat, reg), []).append(float(t.get("pnl") or 0.0))

    out: dict = {}
    for (strat, reg), pnls in buckets.items():
        n = len(pnls)
        wins = sum(p for p in pnls if p > 0)
        losses = abs(sum(p for p in pnls if p <= 0))
        pf = round(wins / losses, 3) if losses > 0 else (None if wins > 0 else 0.0)
        out.setdefault(strat, {})[reg] = {
            "pf": pf,                       # None = "infinite" (no losers)
            "trades": n,
            "expectancy": round(sum(pnls) / n, 2) if n else 0.0,
            "net": round(sum(pnls), 2),
            "status": "ok" if n >= min_trades else "insufficient_data",
        }
    return out


def trusted_fit(fit_map: dict, min_trades: int = 30) -> dict:
    """Reduce a full fit map to only the buckets safe to weight on:
    {strategy: {regime: {pf, trades, source}}}. Drops insufficient-sample and
    infinite-PF (no-loser, untrustworthy) buckets."""
    out: dict = {}
    for strat, regs in fit_map.items():
        for reg, rec in regs.items():
            if rec.get("status") == "ok" and rec.get("pf") is not None and rec["trades"] >= min_trades:
                out.setdefault(strat, {})[reg] = {
                    "pf": rec["pf"], "trades": rec["trades"], "source": "ledger"}
    return out


def write_regime_fit(fit_map: dict, strategies_dir: str = "strategies",
                     min_trades: int = 30) -> list:
    """Merge trusted fits into each strategy's YAML regime_fit block (I/O).
    Returns the list of files updated. Only touches strategies that have a file."""
    trusted = trusted_fit(fit_map, min_trades)
    updated = []
    for strat, regs in trusted.items():
        path = os.path.join(strategies_dir, f"{strat}.yaml")
        if not os.path.isfile(path):
            logger.info(f"no strategy file for {strat}; skipping fit write")
            continue
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        data.setdefault("regime_fit", {})
        for reg, rec in regs.items():
            data["regime_fit"][reg] = rec
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, sort_keys=False)
        os.replace(tmp, path)
        updated.append(path)
        logger.info(f"updated regime_fit for {strat}: {list(regs)}")
    return updated
