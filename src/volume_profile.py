"""
Volume profiles & RVOL (SCRUM-110 / A1) — pure module, no I/O, no Kite, no now().

Time-of-day-adjusted relative volume:
    RVOL(t) = today's cumulative volume at t  /  20-session avg cumulative volume
              at the same time-of-day.

A profile stores, per 15-min bucket boundary, the AVERAGE across recent sessions
of cumulative volume from session open. Bootstrapped once via REST, then rolled
forward from the tick-built candle archive (see docs/specs/A1_volume_profiles.md).

Everything here takes data in and returns values out. `now` is always a
parameter — this module never reads the clock, so it is identical in backtest,
paper and live.
"""
import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd


@dataclass(frozen=True)
class RvolConfig:
    bucket_minutes: int = 15
    window_sessions: int = 20
    min_sessions: int = 10
    staleness_sessions: int = 3
    score_weight: float = 0.4

    @property
    def version(self) -> str:
        blob = json.dumps({
            "bucket_minutes": self.bucket_minutes,
            "window_sessions": self.window_sessions,
            "min_sessions": self.min_sessions,
            "staleness_sessions": self.staleness_sessions,
            "score_weight": self.score_weight,
        }, sort_keys=True)
        return hashlib.sha1(blob.encode()).hexdigest()[:12]


@dataclass(frozen=True)
class VolumeProfile:
    symbol: str
    bucket_minutes: int
    buckets: dict            # "09:30" -> avg cumulative volume at that boundary
    sessions_used: int
    last_session: date
    config_version: str
    session_dates: tuple = field(default=())   # sessions contributing (for rolling)


# ── bucket helpers ────────────────────────────────────────────────────────────

def _session_cumulative(candles: pd.DataFrame, bucket_minutes: int) -> dict:
    """{"HH:MM" boundary -> cumulative volume from session open through that bar}."""
    d = candles.copy()
    d["timestamp"] = pd.to_datetime(d["timestamp"])
    d = d.sort_values("timestamp")
    cum = 0.0
    out = {}
    for _, r in d.iterrows():
        cum += float(r["volume"])
        out[pd.Timestamp(r["timestamp"]).strftime("%H:%M")] = cum
    return out


def _session_of(candles: pd.DataFrame) -> Optional[date]:
    if candles is None or candles.empty:
        return None
    return pd.to_datetime(candles["timestamp"]).iloc[0].date()


# ── build / roll ──────────────────────────────────────────────────────────────

def build_profile(sessions: dict, cfg: RvolConfig,
                  symbol: Optional[str] = None) -> Optional[VolumeProfile]:
    """
    sessions: {date -> 15-min OHLCV frame (session-local)}. Uses the most recent
    `window_sessions`; returns None if fewer than `min_sessions` are available.
    symbol: names the profile (defaults to a 'symbol' column if present, else '?').
    """
    usable = {d: df for d, df in sessions.items() if df is not None and not df.empty}
    if len(usable) < cfg.min_sessions:
        return None
    recent = sorted(usable)[-cfg.window_sessions:]
    if symbol is None:
        last = usable[recent[-1]]
        symbol = str(last["symbol"].iloc[0]) if "symbol" in last.columns else "?"

    sums: dict = {}
    counts: dict = {}
    for d in recent:
        for boundary, cumvol in _session_cumulative(usable[d], cfg.bucket_minutes).items():
            sums[boundary] = sums.get(boundary, 0.0) + cumvol
            counts[boundary] = counts.get(boundary, 0) + 1
    buckets = {b: round(sums[b] / counts[b], 6) for b in sums}   # avg, never zero-filled

    return VolumeProfile(
        symbol=symbol, bucket_minutes=cfg.bucket_minutes, buckets=buckets,
        sessions_used=len(recent), last_session=recent[-1],
        config_version=cfg.version, session_dates=tuple(recent))


def roll_profile(existing: VolumeProfile, new_session: date,
                 candles: pd.DataFrame, cfg: RvolConfig) -> VolumeProfile:
    """Add one session (drop oldest beyond window). Idempotent: rolling the same
    session twice is a no-op."""
    if new_session in existing.session_dates:
        return existing
    # rebuild averages from the retained session set is exact and simple; we only
    # keep dates, so recompute from the incremental contribution.
    dates = list(existing.session_dates) + [new_session]
    dates = sorted(dates)[-cfg.window_sessions:]
    # multiply back to sums, add new, drop dropped — but we lack old per-session
    # data here, so treat the stored buckets as the average over the PRIOR set and
    # blend. To stay exact, callers pass full sessions to build_profile for the
    # window; roll_profile is the online path and uses running average update.
    n_old = existing.sessions_used
    new_cum = _session_cumulative(candles, cfg.bucket_minutes)
    dropped = len(existing.session_dates) + 1 - len(dates)  # 1 if window full
    buckets = dict(existing.buckets)
    for b, v in new_cum.items():
        if b in buckets and dropped == 0:
            buckets[b] = round((buckets[b] * n_old + v) / (n_old + 1), 6)
        elif b in buckets:
            # window full: approximate by replacing one session's weight
            buckets[b] = round(buckets[b] + (v - buckets[b]) / n_old, 6)
        else:
            buckets[b] = round(v, 6)
    return VolumeProfile(
        symbol=existing.symbol, bucket_minutes=cfg.bucket_minutes, buckets=buckets,
        sessions_used=min(n_old + (1 if dropped == 0 else 0), cfg.window_sessions),
        last_session=new_session, config_version=cfg.version,
        session_dates=tuple(dates))


# ── RVOL ──────────────────────────────────────────────────────────────────────

def _trading_days_between(a: date, b: date) -> int:
    """Weekday count between a (exclusive) and b (inclusive). Holiday-agnostic —
    a slightly generous staleness bound is safe (worst case: one extra day)."""
    days, cur = 0, a
    while cur < b:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            days += 1
    return days


def rvol(profile: Optional[VolumeProfile], cum_vol_now: float,
         now: datetime, cfg: RvolConfig) -> Optional[float]:
    """
    Interpolate the profile's cumulative-volume denominator at `now` and return
    today's cumulative / that denominator. None if unusable (stale, pre-open,
    zero denominator, or no profile).
    """
    if profile is None or not profile.buckets:
        return None
    if _trading_days_between(profile.last_session, now.date()) > cfg.staleness_sessions:
        return None

    minutes_now = now.hour * 60 + now.minute
    pairs = sorted((int(b[:2]) * 60 + int(b[3:]), v) for b, v in profile.buckets.items())
    if minutes_now < pairs[0][0]:
        return None                                     # before first boundary
    denom = None
    for i, (m, v) in enumerate(pairs):
        if minutes_now == m:
            denom = v
            break
        if minutes_now < m:
            pm, pv = pairs[i - 1]
            frac = (minutes_now - pm) / (m - pm) if m > pm else 0.0
            denom = pv + (v - pv) * frac
            break
    if denom is None:
        denom = pairs[-1][1]                            # after last boundary
    if denom <= 0:
        return None
    return round(cum_vol_now / denom, 4)
