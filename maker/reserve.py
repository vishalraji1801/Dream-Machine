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


def screen_candles(df: pd.DataFrame, lock: dict) -> pd.DataFrame:
    """Data strictly BEFORE the cutoff — the ONLY data screen/gauntlet may read."""
    cutoff = pd.to_datetime(lock["cutoff_date"])
    return df[pd.to_datetime(df["timestamp"]) < cutoff].reset_index(drop=True)


def reserve_candles(df: pd.DataFrame, lock: dict) -> pd.DataFrame:
    """Post-cutoff data. Raises unless the reserve is unlocked (inside evaluate_once)."""
    if not _UNLOCKED:
        raise PermissionError(
            "reserve data may only be read inside reserve.evaluate_once (RULE 2)")
    cutoff = pd.to_datetime(lock["cutoff_date"])
    return df[pd.to_datetime(df["timestamp"]) >= cutoff].reset_index(drop=True)


def _default_evaluator(candidate, reserve_by_symbol: dict, cfg: dict) -> dict:
    from maker.screen import screen_candidate
    _, _, m = screen_candidate(candidate, reserve_by_symbol, cfg)
    return m


def evaluate_once(candidate, family: str, candles_by_symbol: dict, lock: dict,
                  registry, n_effective: int, cfg: dict, evaluator=None) -> tuple[str, dict]:
    """The family's single reserve shot. Refuses if any RESERVE row exists for the
    family. PASS requires pf >= pf_required(N) AND trades >= 20 AND net > 0."""
    global _UNLOCKED
    for row in registry.rows():
        if row["family"] == family and row["stage"] == "RESERVE":
            raise RuntimeError(f"family {family} already used its single reserve shot (RULE 2)")
    bar = pf_required(n_effective)
    _UNLOCKED = True
    try:
        reserve_by_symbol = {s: reserve_candles(df, lock) for s, df in candles_by_symbol.items()}
        metrics = (evaluator or _default_evaluator)(candidate, reserve_by_symbol, cfg)
    finally:
        _UNLOCKED = False
    passed = metrics["pf"] >= bar and metrics["trades"] >= 20 and metrics["net"] > 0
    status = "ALIVE" if passed else "DEAD"
    registry.record(candidate.cid, family, "RESERVE", status, pf_required=bar, metrics=metrics)
    return status, metrics
