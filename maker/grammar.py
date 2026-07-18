"""maker/grammar.py — Candidate + compile() (Strategy Maker, spec section 2).

A Candidate is a choice of one block per slot with concrete params. compile() snaps
it into ONE pure function fn(symbol, df, cfg) -> TradeSignal, conforming to the
existing framework so the whole gauntlet / cost model / paper engine work unchanged.

Determinism: same cid always compiles to byte-identical behavior. cid is a stable
hash of (direction + blocks + params), so a modified candidate is a NEW candidate.

Block evaluators reuse the existing pinned indicators in src.strategy where possible;
blocks not yet implemented raise NotImplementedError (filled as indicators land in
later commits) — the generator simply does not emit them until then.
"""
import hashlib
import json
from dataclasses import dataclass, field
from typing import Callable, Optional

import pandas as pd

from maker.blocks import BLOCKS, CONDITION_SLOTS


@dataclass(frozen=True)
class BlockInstance:
    name: str
    params: dict          # concrete chosen values (each a member of the block's grid)


@dataclass(frozen=True)
class Candidate:
    cid: str
    direction: str        # long | short | both
    blocks: dict          # slot -> BlockInstance
    n_conditions: int
    n_params: int
    rationale: str
    cost_check: dict = field(default_factory=dict)


def _canonical(direction: str, blocks: dict) -> str:
    payload = {
        "dir": direction,
        "blocks": {slot: {"name": bi.name,
                          "params": {k: bi.params[k] for k in sorted(bi.params)}}
                   for slot, bi in sorted(blocks.items())},
    }
    return json.dumps(payload, sort_keys=True, default=list)


def _cid(direction: str, blocks: dict) -> str:
    return hashlib.sha256(_canonical(direction, blocks).encode()).hexdigest()[:16]


def make_candidate(direction: str, blocks: dict) -> Candidate:
    """blocks: {slot: (block_name, {param: value})}. Validates params against the
    block's declared grid, computes cid / condition & param counts / joined rationale."""
    if direction not in ("long", "short", "both"):
        raise ValueError(f"bad direction {direction!r}")
    inst, n_params = {}, 0
    for slot, (name, params) in blocks.items():
        b = BLOCKS[name]
        if b.slot != slot:
            raise ValueError(f"block {name!r} is slot {b.slot!r}, not {slot!r}")
        for p, v in params.items():
            if p not in b.params or v not in b.params[p]:
                raise ValueError(f"{name}.{p}={v!r} not in grid {b.params.get(p)}")
        inst[slot] = BlockInstance(name, dict(params))
        n_params += len(params)
    n_conditions = sum(1 for slot in inst if slot in CONDITION_SLOTS)
    rationale = " ".join(BLOCKS[bi.name].rationale for bi in inst.values())
    return Candidate(_cid(direction, inst), direction, inst, n_conditions, n_params, rationale)


# ── indicator helpers (reuse the existing pinned math) ────────────────────────

def _sma(df, n):
    return df["close"].rolling(n).mean()


def _bbwidth_pctile(df, period=20, lookback=100):
    mid = df["close"].rolling(period).mean()
    width = df["close"].rolling(period).std() / mid
    if len(width.dropna()) < lookback:
        return None
    cur = width.iloc[-1]
    if cur != cur:
        return None
    return float((width.iloc[-lookback:] < cur).mean() * 100)


# ── block evaluators: (df, params) -> result ──────────────────────────────────
# regime/setup/trigger return a bool (or a level dict for setups); exits return
# (stop, target) given (df, entry, direction). Unimplemented -> NotImplementedError.

def _regime_ok(name, params, df):
    last = float(df["close"].iloc[-1])
    if name == "trend_side":
        sma = _sma(df, params["ma"]).iloc[-1]
        if sma != sma:
            return False
        return last > sma if params["side"] == "above" else last < sma
    if name == "bb_width_pctile":
        pct = _bbwidth_pctile(df)
        if pct is None:
            return False
        return pct < params["below"] if "below" in params else pct > params["above"]
    raise NotImplementedError(f"regime block {name!r} not implemented yet")


def _setup_level(name, params, df):
    """Return an entry-reference level (float) if the setup is present, else None."""
    close = df["close"]
    last = float(close.iloc[-1])
    if name == "nday_extreme":
        n = params["lookback"]
        if len(df) < n + 1:
            return None
        if params["side"] == "high" and last >= float(close.iloc[-n:].max()):
            return last
        if params["side"] == "low" and last <= float(close.iloc[-n:].min()):
            return last
        return None
    if name == "compression":
        pct = _bbwidth_pctile(df)
        if pct is None or pct >= params["bbw_pctile_below"]:
            return None
        return last
    if name == "band_touch":
        period, sd = params["bollinger"]
        mid = close.rolling(period).mean().iloc[-1]
        std = close.rolling(period).std().iloc[-1]
        if mid != mid:
            return None
        lower, upper = mid - sd * std, mid + sd * std
        if params["side"] == "lower" and last < lower:
            return last
        if params["side"] == "upper" and last > upper:
            return last
        return None
    raise NotImplementedError(f"setup block {name!r} not implemented yet")


def _trigger_ok(name, params, df, level):
    close = df["close"]
    last = float(close.iloc[-1])
    if name == "breakout_close":
        return last >= level if level is not None else False
    if name == "limit_below":
        return True                      # limit entry handled by the fill model
    if name == "resume_new_high":
        w = params["within_bars"]
        return last >= float(df["high"].iloc[-w - 1:-1].max()) if len(df) > w + 1 else False
    raise NotImplementedError(f"trigger block {name!r} not implemented yet")


def _exit_levels(name, params, df, entry, direction):
    from src.strategy import _atr
    long = direction == "long"
    if name == "atr_trail":
        atr = _atr(df, params.get("period", 14))
        stop = entry - params["mult"] * atr if long else entry + params["mult"] * atr
        target = entry + 20 * atr if long else entry - 20 * atr    # far; trail is the exit
        return round(stop, 2), round(target, 2)
    if name == "r_multiple":
        atr = _atr(df, 14)
        risk = 1.5 * atr
        stop = entry - risk if long else entry + risk
        target = entry + params["r"] * risk if long else entry - params["r"] * risk
        return round(stop, 2), round(target, 2)
    if name == "opposite_band":
        period, sd = params["bollinger"]
        mid = float(df["close"].rolling(period).mean().iloc[-1])
        std = float(df["close"].rolling(period).std().iloc[-1])
        atr = _atr(df, 14)
        stop = entry - 3 * atr if long else entry + 3 * atr
        target = mid                     # revert to the mean
        return round(stop, 2), round(target, 2)
    raise NotImplementedError(f"exit block {name!r} not implemented yet")


def compile(candidate: Candidate) -> Callable:
    """Snap the candidate into a pure fn(symbol, df, cfg) -> TradeSignal."""
    c = candidate
    direction = "long" if c.direction == "both" else c.direction  # CNC: long only anyway
    setup = c.blocks["setup"]
    trigger = c.blocks["trigger"]
    exit_b = c.blocks["exit"]
    regime = c.blocks.get("regime")

    def fn(symbol: str, df: pd.DataFrame, cfg: dict):
        from src.strategy import TradeSignal, _hold
        if df is None or len(df) < 210:
            return _hold(symbol, "insufficient_data")
        if regime is not None and not _regime_ok(regime.name, regime.params, df):
            return _hold(symbol, "regime_block")
        level = _setup_level(setup.name, setup.params, df)
        if level is None:
            return _hold(symbol, "no_setup")
        if not _trigger_ok(trigger.name, trigger.params, df, level):
            return _hold(symbol, "no_trigger")
        entry = float(df["close"].iloc[-1])
        stop, target = _exit_levels(exit_b.name, exit_b.params, df, entry, direction)
        d = "BUY" if direction == "long" else "SELL"
        if (d == "BUY" and not stop < entry < target) or (d == "SELL" and not target < entry < stop):
            return _hold(symbol, "bad_levels")
        return TradeSignal(d, symbol, round(entry, 2), stop, target, f"maker:{c.cid}")

    fn.cid = c.cid
    fn.__name__ = f"maker_{c.cid}"
    return fn
