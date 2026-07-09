from datetime import date, timedelta
from unittest.mock import MagicMock

import backfill_profiles as bf
from src.volume_profile import RvolConfig


def test_plan_requests_only_missing_sessions(tmp_path):
    from src.profile_store import ProfileStore
    from src.volume_profile import build_profile
    import pandas as pd
    store = ProfileStore(directory=str(tmp_path))

    end = date(2026, 7, 3)   # Friday
    cfg = RvolConfig(window_sessions=5, min_sessions=1)
    wanted = bf._recent_trading_days(5, end)            # 5 trading days up to 07-03
    # seed a profile that already has the last 2 of those days
    have = wanted[-2:]
    sess = {d: pd.DataFrame({
        "timestamp": pd.date_range(f"{d} 09:15", periods=2, freq="15min", tz="Asia/Kolkata"),
        "open": [1.0, 1.0], "high": [1.0, 1.0], "low": [1.0, 1.0],
        "close": [1.0, 1.0], "volume": [10.0, 10.0]}) for d in have}
    store.save(build_profile(sess, RvolConfig(window_sessions=5, min_sessions=1), symbol="X"))

    p = bf.plan(store, ["X"], cfg, end)
    assert p["X"] == wanted[:-2]                        # exactly the 3 missing days


def test_recent_trading_days_skips_weekends():
    days = bf._recent_trading_days(5, date(2026, 7, 3))  # Fri
    assert all(d.weekday() < 5 for d in days)
    assert len(days) == 5
    assert days[-1] == date(2026, 7, 3)
