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
    sleeve: str = "swing"       # swing | intraday
    timeframe: str = "1d"       # swing: 1d/1w  ·  intraday: 5m/15m
    product: str = "delivery"   # derived: swing -> delivery(CNC), intraday -> intraday(MIS)
    cost_check: dict = field(default_factory=dict)


def product_for_sleeve(sleeve: str) -> str:
    return "intraday" if sleeve == "intraday" else "delivery"


def default_timeframe(sleeve: str) -> str:
    return "15m" if sleeve == "intraday" else "1d"


def _canonical(direction, blocks, sleeve="swing", timeframe="1d") -> str:
    payload = {
        "dir": direction, "sleeve": sleeve, "tf": timeframe,
        "blocks": {slot: {"name": bi.name,
                          "params": {k: bi.params[k] for k in sorted(bi.params)}}
                   for slot, bi in sorted(blocks.items())},
    }
    return json.dumps(payload, sort_keys=True, default=list)


def _cid(direction, blocks, sleeve="swing", timeframe="1d") -> str:
    return hashlib.sha256(_canonical(direction, blocks, sleeve, timeframe).encode()).hexdigest()[:16]


def make_candidate(direction: str, blocks: dict, sleeve: str = "swing",
                   timeframe: str = None) -> Candidate:
    """blocks: {slot: (block_name, {param: value})}. Validates params against the
    block's declared grid, computes cid / condition & param counts / joined rationale.
    sleeve selects product (swing->delivery/CNC, intraday->MIS) and default timeframe."""
    if direction not in ("long", "short", "both"):
        raise ValueError(f"bad direction {direction!r}")
    if sleeve not in ("swing", "intraday"):
        raise ValueError(f"bad sleeve {sleeve!r}")
    timeframe = timeframe or default_timeframe(sleeve)
    product = product_for_sleeve(sleeve)
    # intraday MUST carry the square_off hold block (hard MIS exit) — same
    # unconstructible-if-absent enforcement as parsimony (section 11.3).
    if sleeve == "intraday":
        hold = blocks.get("hold")
        if not hold or hold[0] != "square_off":
            raise ValueError("intraday candidates must include the square_off hold block")

    inst, n_params = {}, 0
    for slot, (name, params) in blocks.items():
        b = BLOCKS[name]
        if b.slot != slot:
            raise ValueError(f"block {name!r} is slot {b.slot!r}, not {slot!r}")
        if sleeve not in b.sleeves:
            raise ValueError(f"block {name!r} is not valid for sleeve {sleeve!r}")
        for p, v in params.items():
            if p not in b.params or v not in b.params[p]:
                raise ValueError(f"{name}.{p}={v!r} not in grid {b.params.get(p)}")
        inst[slot] = BlockInstance(name, dict(params))
        # a param counts against the budget only if it is genuinely TUNABLE — i.e. its
        # grid offers more than one value. A single-value grid (e.g. period:[14]) is
        # fixed structure, not a knob.
        n_params += sum(1 for p in params if len(b.params[p]) > 1)
    n_conditions = sum(1 for slot in inst if slot in CONDITION_SLOTS)
    if n_conditions > 3:
        raise ValueError(f"parsimony (RULE 3): {n_conditions} condition blocks > 3")
    if n_params > 4:
        raise ValueError(f"parsimony (RULE 3): {n_params} tunable params > 4")
    rationale = " ".join(BLOCKS[bi.name].rationale for bi in inst.values())
    return Candidate(_cid(direction, inst, sleeve, timeframe), direction, inst,
                     n_conditions, n_params, rationale, sleeve, timeframe, product)


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


# ── candlestick shape helpers (pure, single-bar) ──────────────────────────────
# A white hammer = small body in the upper part of the range with a long lower wick
# (sellers pushed down, buyers reclaimed → rejection of lower prices). A doji = an
# indecision bar whose open ≈ close. Both are entry-confirmation candles.

def _is_hammer_white(o, h, l, c):
    rng = h - l
    if rng <= 0:
        return False
    body = abs(c - o)
    lower_wick = min(o, c) - l
    upper_wick = h - max(o, c)
    return (c >= o                     # white/bullish body
            and body <= 0.4 * rng      # small real body
            and lower_wick >= 2 * body # long lower wick
            and upper_wick <= body)    # little to no upper wick


def _is_doji(o, h, l, c):
    rng = h - l
    if rng <= 0:
        return False
    return abs(c - o) <= 0.1 * rng     # open ≈ close relative to the range


def _is_bullish_engulfing(po, pc, o, c):
    # prior bar down, current bar up and its body fully engulfs the prior body — buyers
    # decisively overwhelmed the previous session's sellers.
    return pc < po and c > o and o <= pc and c >= po


def _is_morning_star(o1, c1, o2, c2, o3, c3):
    # bar1 a strong down candle; bar2 a small indecision body (the star); bar3 a strong up
    # candle closing back above bar1's midpoint — a classic three-bar bottoming reversal.
    body1 = o1 - c1
    small_star = abs(c2 - o2) <= 0.5 * abs(body1) if body1 else False
    return (c1 < o1                         # bar1 bearish
            and small_star                  # bar2 small body
            and c3 > o3                      # bar3 bullish
            and c3 > (o1 + c1) / 2)          # closes back above bar1 midpoint


def _is_shooting_star(o, h, l, c):
    # bearish mirror of the hammer: small body at the BOTTOM of the range with a long upper
    # wick (buyers pushed up, sellers reclaimed) — a rejection of higher prices.
    rng = h - l
    if rng <= 0:
        return False
    body = abs(c - o)
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l
    return (c <= o                     # red/bearish body
            and body <= 0.4 * rng      # small real body
            and upper_wick >= 2 * body # long upper wick
            and lower_wick <= body)    # little to no lower wick


# ── intraday session helpers (the intraday df carries a 'timestamp' column) ────
# All are computed relative to the CURRENT session (same date as the last bar), so a
# rolling window that spans several days still measures today's opening range / VWAP.

def _ts(df):
    return pd.to_datetime(df["timestamp"])


def _session_mask(df):
    d = _ts(df).dt.date
    return d == d.iloc[-1]


def _session_vwap(df):
    """VWAP of the current session up to the last bar, or None (no volume)."""
    s = df[_session_mask(df)]
    vol = s["volume"].astype(float)
    cv = float(vol.cumsum().iloc[-1]) if len(vol) else 0.0
    if cv <= 0:
        return None
    tp = (s["high"] + s["low"] + s["close"]) / 3
    return float((tp * vol).cumsum().iloc[-1] / cv)


def _parse_hm(s):
    from datetime import time as _t
    h, m = s.split(":")
    return _t(int(h), int(m))


# ── block evaluators: (df, params) -> result ──────────────────────────────────
# regime/setup/trigger return a bool (or a level dict for setups); exits return
# (stop, target) given (df, entry, direction). Unimplemented -> NotImplementedError.

def _regime_ok(name, params, df):
    last = float(df["close"].iloc[-1])
    if name == "time_window":                  # intraday: session-of-day filter
        start, end = params["allow"]
        return _parse_hm(start) <= _ts(df).iloc[-1].time() <= _parse_hm(end)
    if name == "skip_open_minutes":            # intraday: avoid the first N minutes
        s = df[_session_mask(df)]
        if len(s) == 0:
            return False
        mins = (_ts(df).iloc[-1] - _ts(s).iloc[0]).total_seconds() / 60.0
        return mins >= params["min"]
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
    if name == "adx_band":
        from indicators.core import adx
        val = adx(df, 14).iloc[-1]
        if val != val:                         # NaN during warmup
            return False
        return params["min"] <= float(val) <= params["max"]
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
        # A squeeze is a STATE, not an entry. Return the top of the contraction range as
        # the breakout LEVEL, so breakout_close fires only on a real expansion out of the
        # squeeze — not every compressed bar (the tautology that made this over-trade).
        w = params.get("min_bars", 10)
        if len(df) < w + 1:
            return None
        return float(df["high"].iloc[-(w + 1):-1].max())
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
    if name == "objective_level":
        # Objective S/R the whole market watches — no detection params, so it cannot be
        # curve-fit (section 15, tier-1). Returns the level; the trigger decides the break.
        if len(df) < 2:
            return None
        lvl = params["level"]
        if lvl == "pdh":
            return float(df["high"].iloc[-2])          # prior bar's high
        if lvl == "pdl":
            return float(df["low"].iloc[-2])
        if lvl == "pdc":
            return float(df["close"].iloc[-2])
        if lvl == "round":                             # nearest psychological round number
            step = 10 if last < 100 else 50 if last < 1000 else 100 if last < 5000 else 500
            return round(last / step) * float(step)
        return None
    if name == "pullback_depth":
        # A measured pullback INSIDE an uptrend: price still above the trend MA but a
        # defined % off its recent swing high — enters strength at a discount.
        ma = params["within_trend_ma"]
        if len(df) < ma + 1:
            return None
        sma = _sma(df, ma).iloc[-1]
        if sma != sma or last < sma:                   # must be in an uptrend
            return None
        recent_high = float(df["high"].iloc[-60:].max())
        if recent_high <= 0:
            return None
        drawdown = (recent_high - last) / recent_high * 100
        return last if drawdown >= params["from_high_pct"] else None
    if name == "flush":
        # A sharp multi-bar flush: close down >= pct% over the last `bars` bars. The
        # liquidity-vacuum overreaction that tends to snap back.
        pct, bars = params["down_pct_in_bars"]
        if len(df) < bars + 1:
            return None
        ref = float(df["close"].iloc[-(bars + 1)])
        if ref <= 0:
            return None
        drop = (ref - last) / ref * 100
        return last if drop >= pct else None
    if name == "gap":
        # An overnight gap of >= gap_pct_min% in the given direction — an information
        # shock; the trigger/direction decide continuation vs fade.
        if len(df) < 2:
            return None
        prev_close = float(close.iloc[-2])
        today_open = float(df["open"].iloc[-1])
        if prev_close <= 0:
            return None
        gap_pct = (today_open - prev_close) / prev_close * 100
        if params["direction"] == "up":
            return last if gap_pct >= params["gap_pct_min"] else None
        return last if -gap_pct >= params["gap_pct_min"] else None
    if name == "double_bottom":
        # Two comparable swing lows with a peak between them = a tested support that
        # reverses. Uses CONFIRMED pivots (no look-ahead); returns the neckline (middle
        # peak) as the breakout level so the trigger fires on the reversal confirmation.
        from indicators.swings import swing_pivots
        n = params["swing_n"]
        highs, lows = swing_pivots(df, n)
        if len(lows) < 2:
            return None
        (p1, v1), (p2, v2) = lows[-2], lows[-1]
        if v1 <= 0 or abs(v2 - v1) / v1 * 100 > params["tol_pct"]:
            return None                                # lows not comparable
        mids = [v for p, v in highs if p1 < p < p2]
        if not mids:                                   # need a peak between the two lows
            return None
        if last < v2:                                  # price broke below the second low
            return None
        return float(max(mids))                        # neckline
    if name == "inv_head_shoulders":
        # three confirmed swing lows: middle (head) the deepest, shoulders higher and
        # roughly level; neckline = the peaks between them. Bullish reversal on the break.
        from indicators.swings import swing_pivots
        n = params["swing_n"]
        highs, lows = swing_pivots(df, n)
        if len(lows) < 3:
            return None
        (lp, lv), (hp, hv), (rp, rv) = lows[-3], lows[-2], lows[-1]
        if not (hv < lv and hv < rv):                  # head must be the deepest
            return None
        if lv <= 0 or abs(rv - lv) / lv * 100 > params["shoulder_tol_pct"]:
            return None                                # shoulders not roughly level
        necks = [v for p, v in highs if lp < p < rp]
        if not necks or last < rv:
            return None
        return float(max(necks))                       # neckline
    if name == "fib_pullback":
        # a pullback to the 50/61.8% retracement of the last confirmed up-swing (ABCD /
        # harmonic entry). Present once price has retraced at least to that level.
        from indicators.fib import pullback_to_fib
        lvl = pullback_to_fib(df, params["swing_n"], params["level"])
        if lvl is None:
            return None
        return last if last <= lvl else None
    # ── intraday setups (section 11.2) ────────────────────────────────────────
    if name == "opening_range":
        # the break level of the first `window_min` minutes of TODAY's session.
        s = df[_session_mask(df)]
        if len(s) < 2:
            return None
        or_end = _ts(s).iloc[0] + pd.Timedelta(minutes=params["window_min"])
        or_bars = s[_ts(s) < or_end]
        if len(or_bars) == 0 or len(or_bars) == len(s):     # still inside the OR
            return None
        if params["break_side"] == "low":
            return float(or_bars["low"].min())
        return float(or_bars["high"].max())                 # "high" / "gap_aligned"
    if name == "vwap_relation":
        v = _session_vwap(df)
        if v is None:
            return None
        d = params["min_dist_pct"]
        st = params["state"]
        if st == "hold_above":
            return last if last >= v * (1 + d / 100) else None
        if st == "break_below":
            return last if last <= v * (1 - d / 100) else None
        if st == "reclaim":                                 # crossed up through VWAP
            prev = float(close.iloc[-2]) if len(close) > 1 else last
            return last if prev < v <= last else None
        return None
    if name == "prior_day_level":
        d = _ts(df).dt.date
        prior = d[d < d.iloc[-1]]
        if prior.empty:
            return None
        ps = df[d == prior.iloc[-1]]                         # the previous session
        lvl = params["level"]
        if lvl == "pdh":
            return float(ps["high"].max())
        if lvl == "pdl":
            return float(ps["low"].min())
        return float(ps["close"].iloc[-1])                  # pdc
    if name == "intraday_flush":
        pct, mins = params["down_pct_in_min"]
        w = df[_ts(df) >= _ts(df).iloc[-1] - pd.Timedelta(minutes=mins)]
        if len(w) < 2:
            return None
        ref = float(w["close"].iloc[0])
        if ref <= 0:
            return None
        return last if (ref - last) / ref * 100 >= pct else None
    raise NotImplementedError(f"setup block {name!r} not implemented yet")


def _trigger_ok(name, params, df, level, direction="long"):
    close = df["close"]
    last = float(close.iloc[-1])
    short = direction == "short"
    if name == "breakout_close":                 # break the level in the TRADE direction
        if level is None:
            return False
        return last <= level if short else last >= level
    if name == "limit_below":
        return True                      # limit entry handled by the fill model
    if name == "resume_new_high":                # new extreme in the trade direction
        w = params["within_bars"]
        if len(df) <= w + 1:
            return False
        if short:
            return last <= float(df["low"].iloc[-w - 1:-1].min())
        return last >= float(df["high"].iloc[-w - 1:-1].max())
    if name == "confirm_candle":
        # Require the entry bar to be a bullish reversal candle that closed strong. On
        # daily data VWAP is approximated by the bar midpoint (H+L)/2, so above_vwap
        # means the close finished in the upper half — buyers showed up before entry.
        o = float(df["open"].iloc[-1]); h = float(df["high"].iloc[-1])
        l = float(df["low"].iloc[-1]); c = last
        if params.get("above_vwap") and not c > (h + l) / 2:
            return False
        accept = params["accept"]
        if "hammer_white" in accept and _is_hammer_white(o, h, l, c):
            return True
        if "doji" in accept and _is_doji(o, h, l, c):
            return True
        return False
    if name == "bullish_reversal_candle":
        pat = params["pattern"]
        if pat == "engulfing":
            if len(df) < 2:
                return False
            po = float(df["open"].iloc[-2]); pc = float(df["close"].iloc[-2])
            o = float(df["open"].iloc[-1])
            return _is_bullish_engulfing(po, pc, o, last)
        if pat == "morning_star":
            if len(df) < 3:
                return False
            o1 = float(df["open"].iloc[-3]); c1 = float(df["close"].iloc[-3])
            o2 = float(df["open"].iloc[-2]); c2 = float(df["close"].iloc[-2])
            o3 = float(df["open"].iloc[-1])
            return _is_morning_star(o1, c1, o2, c2, o3, last)
        return False
    # ── intraday triggers (section 11.2) ──────────────────────────────────────
    if name == "new_extreme_after_pullback":     # new extreme in the trade direction
        w = params["pullback_bars"]
        if len(df) < w + 2:
            return False
        if short:
            return last <= float(df["low"].iloc[-w - 1:-1].min())
        return last >= float(df["high"].iloc[-w - 1:-1].max())
    if name == "candle_confirm_1m":
        o = float(df["open"].iloc[-1]); h = float(df["high"].iloc[-1])
        l = float(df["low"].iloc[-1]); c = last
        v = _session_vwap(df)
        if params.get("above_vwap"):             # confirm on the correct side of VWAP
            if v is None or (c >= v if short else c <= v):
                return False
        accept = params["accept"]
        if short:                                # bearish mirror: shooting star / doji
            if "hammer_white" in accept and _is_shooting_star(o, h, l, c):
                return True
            if "doji" in accept and _is_doji(o, h, l, c):
                return True
            return False
        if "hammer_white" in accept and _is_hammer_white(o, h, l, c):
            return True
        if "doji" in accept and _is_doji(o, h, l, c):
            return True
        return False
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
        if not _trigger_ok(trigger.name, trigger.params, df, level, direction):
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
