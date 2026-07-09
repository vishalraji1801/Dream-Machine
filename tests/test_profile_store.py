from datetime import date

import pandas as pd

from src.profile_store import ProfileStore
from src.volume_profile import RvolConfig, build_profile


def _sessions(days, per_bar):
    return {d: pd.DataFrame({
        "timestamp": pd.date_range(f"{d} 09:15", periods=len(per_bar), freq="15min", tz="Asia/Kolkata"),
        "open": [100.0]*len(per_bar), "high": [101.0]*len(per_bar),
        "low": [99.0]*len(per_bar), "close": [100.0]*len(per_bar), "volume": per_bar})
        for d in days}


def _days(n, start=date(2026, 6, 1)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d = date.fromordinal(d.toordinal() + 1)
    return out


def test_save_load_roundtrip(tmp_path):
    store = ProfileStore(directory=str(tmp_path))
    p = build_profile(_sessions(_days(12), [100.0, 200.0]), RvolConfig(min_sessions=10), symbol="ACME")
    store.save(p)
    loaded = store.load("ACME")
    # symbol is "?" in fixture; save/load by that key
    assert loaded is not None
    assert loaded.buckets == p.buckets
    assert loaded.last_session == p.last_session
    assert set(loaded.session_dates) == set(p.session_dates)


def test_load_missing_returns_none(tmp_path):
    assert ProfileStore(directory=str(tmp_path)).load("NOPE") is None


def test_sessions_present(tmp_path):
    store = ProfileStore(directory=str(tmp_path))
    days = _days(12)
    p = build_profile(_sessions(days, [100.0]), RvolConfig(min_sessions=10), symbol="ACME")
    store.save(p)
    present = store.sessions_present(p.symbol)
    assert present == set(p.session_dates)
