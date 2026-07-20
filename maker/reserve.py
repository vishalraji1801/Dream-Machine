"""maker/reserve.py — the locked, single-shot reserve holdout (Strategy Maker, RULE 2).

The most recent months of every symbol's history are cut off before generation begins.
No generator, screener, tuner, or gauntlet run may read past the cutoff — screen/gauntlet
call screen_candles() (strictly pre-cutoff), and reserve_candles() raises unless the
reserve is transiently unlocked inside evaluate_once().

A candidate that passes the gauntlet gets ONE reserve evaluation per FAMILY, ever.
FAIL -> the family is DEAD (all TF/param variants, permanent). PASS -> ALIVE at the
evaluated combo. This is deliberately built BEFORE the gauntlet wiring so that at no
point in the codebase's history could reserve data leak into a search-stage run.
"""
import hashlib
import json
import os
from datetime import datetime
from functools import partial

import pandas as pd

from maker.bar import pf_required

# Reserve data is readable ONLY while this flag is set, and it is set only inside
# evaluate_once(). Any other caller that reaches reserve_candles() gets a PermissionError.
_UNLOCKED = False


def write_lock(cutoff_date: str, symbols, path: str = "data_cache/reserve_lock.json") -> dict:
    """Write reserve_lock.json ONCE. Refuses to overwrite an existing lock."""
    if os.path.exists(path):
        raise FileExistsError(f"reserve lock already exists at {path} — locked once (RULE 2)")
    syms = sorted(symbols)
    h = hashlib.sha256((cutoff_date + "|" + ",".join(syms)).encode()).hexdigest()[:16]
    lock = {"cutoff_date": cutoff_date, "symbols": syms, "hash": h,
            "created_at": datetime.now().isoformat(timespec="seconds")}
    with open(path, "w") as f:
        json.dump(lock, f, indent=2)
    return lock


def load_lock(path: str = "data_cache/reserve_lock.json") -> dict:
    with open(path) as f:
        return json.load(f)


def _ts_naive(df: pd.DataFrame) -> pd.Series:
    """Timestamps as tz-naive datetimes. Real store bars are tz-aware (IST, +05:30);
    the cutoff is a plain date — strip the tz so the comparison is valid and date-based."""
    ts = pd.to_datetime(df["timestamp"])
    if getattr(ts.dt, "tz", None) is not None:
        ts = ts.dt.tz_localize(None)
    return ts


def screen_candles(df: pd.DataFrame, lock: dict) -> pd.DataFrame:
    """Data strictly BEFORE the cutoff — the ONLY data screen/gauntlet may read."""
    cutoff = pd.to_datetime(lock["cutoff_date"])
    return df[_ts_naive(df) < cutoff].reset_index(drop=True)


def reserve_candles(df: pd.DataFrame, lock: dict) -> pd.DataFrame:
    """Post-cutoff data. Raises unless the reserve is unlocked (inside evaluate_once)."""
    if not _UNLOCKED:
        raise PermissionError(
            "reserve data may only be read inside reserve.evaluate_once (RULE 2)")
    cutoff = pd.to_datetime(lock["cutoff_date"])
    return df[_ts_naive(df) >= cutoff].reset_index(drop=True)


# The reserve TEST window (post-cutoff) is only months long, but a compiled candidate
# needs screen.WINDOW bars of warmup or it HOLDS forever — producing 0 trades and an
# automatic (false) DEAD. So the reserve evaluation warms up on the pre-cutoff TAIL and
# scores ONLY trades ENTERED post-cutoff: proper walk-forward OOS. Pre-cutoff bars are
# context the screen/gauntlet already saw — never leakage; the single-shot verdict still
# rests entirely on unseen post-cutoff P&L.
RESERVE_WARMUP = 260             # >= screen.WINDOW (220), with margin


def _reserve_eval_frame(df: pd.DataFrame, lock: dict, warmup: int = RESERVE_WARMUP) -> pd.DataFrame:
    """Pre-cutoff warmup tail + post-cutoff test bars. Gated exactly like reserve_candles
    (RULE 2): only readable inside evaluate_once. The warmup bars give the rolling window
    its context; _default_evaluator discards any trades that open before the cutoff."""
    if not _UNLOCKED:
        raise PermissionError(
            "reserve data may only be read inside reserve.evaluate_once (RULE 2)")
    ts = _ts_naive(df)
    cutoff = pd.to_datetime(lock["cutoff_date"])
    warm = df[ts < cutoff].tail(warmup)
    post = df[ts >= cutoff]
    return pd.concat([warm, post], ignore_index=True)


def _default_evaluator(candidate, eval_by_symbol: dict, cfg: dict, cutoff) -> dict:
    """One honest event-driven backtest over warmup+post-cutoff bars, scored on ONLY the
    trades entered on/after the cutoff — the shared walk-forward primitive (maker.screen)."""
    from maker.screen import oos_metrics
    return oos_metrics(candidate, eval_by_symbol, pd.to_datetime(cutoff), cfg)


# ── effective reserve verdict (append-only supersession, RULE 2) ──────────────
# The log is append-only, so an invalid single-shot (e.g. one a bug recorded) is never
# deleted — it is SUPERSEDED. A RESERVE row with status "VOID" invalidates every reserve
# verdict for that family recorded before it; the family may then take a fresh shot, whose
# result is appended after the VOID. The EFFECTIVE verdict is the latest ALIVE/DEAD row
# after the last VOID (or None = no active shot). This preserves the full audit trail —
# bug verdict, its invalidation, and the real verdict all remain visible.

def reserve_verdict(rows, family: str):
    """The family's effective reserve row (ALIVE/DEAD) honoring VOID supersessions, or None
    if it has no active reserve shot. `rows` must be id-ordered (registry.rows() is)."""
    fam = [r for r in rows if r["family"] == family and r["stage"] == "RESERVE"]
    last_void = max((r["id"] for r in fam if r["status"] == "VOID"), default=0)
    live = [r for r in fam if r["status"] in ("ALIVE", "DEAD") and r["id"] > last_void]
    return live[-1] if live else None


def effective_reserve_table(rows) -> dict:
    """{family: 'ALIVE'|'DEAD'} for every family with an active (non-voided) reserve shot."""
    fams = {r["family"] for r in rows if r["stage"] == "RESERVE"}
    out = {}
    for f in fams:
        v = reserve_verdict(rows, f)
        if v is not None:
            out[f] = v["status"]
    return out


def invalidate_reserve(registry, family: str, reason: str) -> int:
    """Append a VOID marker superseding the family's prior reserve verdict — the
    append-only way to correct an invalid single-shot (RULE 1 + RULE 2 preserved)."""
    current = reserve_verdict(registry.rows(), family)
    cid = current["cid"] if current is not None else ""
    return registry.record(cid, family, "RESERVE", "VOID", notes=f"invalidated: {reason}")


def evaluate_once(candidate, family: str, candles_by_symbol: dict, lock: dict,
                  registry, n_effective: int, cfg: dict, evaluator=None) -> tuple[str, dict]:
    """The family's single reserve shot. Refuses if the family already has an ACTIVE
    (non-voided) reserve verdict. PASS requires pf >= pf_required(N) AND trades >= 20 AND net > 0."""
    global _UNLOCKED
    if reserve_verdict(registry.rows(), family) is not None:
        raise RuntimeError(f"family {family} already used its single reserve shot (RULE 2)")
    bar = pf_required(n_effective)
    _UNLOCKED = True
    try:
        eval_by_symbol = {s: _reserve_eval_frame(df, lock)
                          for s, df in candles_by_symbol.items()}
        cutoff = pd.to_datetime(lock["cutoff_date"])
        ev = evaluator or partial(_default_evaluator, cutoff=cutoff)
        metrics = ev(candidate, eval_by_symbol, cfg)
    finally:
        _UNLOCKED = False
    passed = metrics["pf"] >= bar and metrics["trades"] >= 20 and metrics["net"] > 0
    status = "ALIVE" if passed else "DEAD"
    registry.record(candidate.cid, family, "RESERVE", status, pf_required=bar, metrics=metrics)
    return status, metrics
