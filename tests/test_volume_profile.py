from datetime import date, datetime

import pandas as pd
import pytest

from src.volume_profile import RvolConfig, build_profile, roll_profile, rvol


def _session(day, vols, tz="Asia/Kolkata"):
    """15-min session frame from a list of per-bar volumes starting 09:15."""
    ts = pd.date_range(f"{day} 09:15", periods=len(vols), freq="15min", tz=tz)
    return pd.DataFrame({"timestamp": ts, "open": [100.0] * len(vols),
                         "high": [101.0] * len(vols), "low": [99.0] * len(vols),
                         "close": [100.0] * len(vols), "volume": vols})


def _sessions(n, per_bar_vols, start=date(2026, 6, 1)):
    out = {}
    d = start
    made = 0
    while made < n:
        if d.weekday() < 5:
            out[d] = _session(d.isoformat(), per_bar_vols)
            made += 1
        d = date.fromordinal(d.toordinal() + 1)
    return out


CFG = RvolConfig(window_sessions=20, min_sessions=10)


# ── test 1: golden profile (must never change) ────────────────────────────────

def test_golden_profile():
    # 3 sessions, volumes [100,200,300] per bar -> cumulative [100,300,600]
    sessions = _sessions(3, [100.0, 200.0, 300.0])
    cfg = RvolConfig(window_sessions=20, min_sessions=3)
    p = build_profile(sessions, cfg)
    assert p.buckets["09:15"] == 100.0
    assert p.buckets["09:30"] == 300.0
    assert p.buckets["09:45"] == 600.0
    assert p.sessions_used == 3


# ── test 2: rolling window + idempotency ──────────────────────────────────────

def test_rolling_window_and_idempotency():
    sessions = _sessions(20, [100.0, 100.0])
    p = build_profile(sessions, CFG)
    assert p.sessions_used == 20
    new_day = date(2026, 7, 1)
    p2 = roll_profile(p, new_day, _session(new_day.isoformat(), [100.0, 100.0]), CFG)
    assert p2.sessions_used == 20                       # capped
    assert p2.last_session == new_day
    p3 = roll_profile(p2, new_day, _session(new_day.isoformat(), [100.0, 100.0]), CFG)
    assert p3 is p2 or p3.session_dates == p2.session_dates   # no double-count


# ── test 3: interpolation ─────────────────────────────────────────────────────

def test_interpolation_between_buckets():
    sessions = _sessions(10, [100.0, 200.0])            # cum: 09:15->100, 09:30->300
    p = build_profile(sessions, RvolConfig(window_sessions=20, min_sessions=10))
    # at 09:22 (midway-ish): denom interpolates 100..300. now cum=200 -> rvol<...>
    val = rvol(p, cum_vol_now=200.0, now=datetime(2026, 7, 1, 9, 22), cfg=p_cfg())
    # denom at +7min of 15 = 100 + (300-100)*7/15 = 193.33 -> 200/193.33
    assert val == pytest.approx(200.0 / (100 + 200 * 7 / 15), abs=0.01)


def p_cfg():
    return RvolConfig(window_sessions=20, min_sessions=10, staleness_sessions=99)


# ── test 4: point-in-time (no same-day data) ──────────────────────────────────

def test_point_in_time_excludes_named_day():
    sessions = _sessions(10, [100.0, 100.0])
    p = build_profile(sessions, RvolConfig(window_sessions=20, min_sessions=10))
    day_d = sorted(sessions)[-1]
    # a profile "as of day D" should be built only from sessions strictly before D
    prior = {d: df for d, df in sessions.items() if d < day_d}
    p_prior = build_profile(prior, RvolConfig(window_sessions=20, min_sessions=9))
    assert day_d not in p_prior.session_dates
    assert p_prior.sessions_used == 9


# ── test 5: staleness ─────────────────────────────────────────────────────────

def test_staleness_returns_none():
    from datetime import timedelta
    cfg = RvolConfig(window_sessions=20, min_sessions=10, staleness_sessions=3)
    p = build_profile(_sessions(10, [100.0, 100.0]), cfg)
    fresh = datetime.combine(p.last_session, datetime.min.time()) + timedelta(days=1, hours=10)
    assert rvol(p, 50.0, fresh, cfg) is not None        # next day: usable
    stale = datetime.combine(p.last_session, datetime.min.time()) + timedelta(days=8, hours=10)
    assert rvol(p, 50.0, stale, cfg) is None            # 8 days (>3 trading) later: None


# ── test 6: half day ──────────────────────────────────────────────────────────

def test_half_day_contributes_morning_only():
    full = _sessions(9, [100.0, 100.0, 100.0])
    half_day = date(2026, 7, 1)
    full[half_day] = _session(half_day.isoformat(), [100.0])   # only 09:15 bar
    p = build_profile(full, RvolConfig(window_sessions=20, min_sessions=10))
    # 09:30/09:45 averaged over 9 sessions; 09:15 over 10
    assert p.buckets["09:15"] == 100.0
    assert p.buckets["09:30"] == 200.0                 # unaffected by the half day


# ── test 7: min sessions ──────────────────────────────────────────────────────

def test_min_sessions_returns_none():
    sessions = _sessions(9, [100.0])
    assert build_profile(sessions, RvolConfig(min_sessions=10)) is None


# ── purity guard ──────────────────────────────────────────────────────────────

def test_module_has_no_io_or_kite_imports():
    import src.volume_profile as vp
    src = open(vp.__file__, encoding="utf-8").read()
    assert "kiteconnect" not in src
    assert "datetime.now(" not in src
    assert "open(" not in src.replace("open\":", "")   # no file I/O in the module
