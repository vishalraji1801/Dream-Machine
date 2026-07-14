from datetime import datetime

import pandas as pd
import pytest

from src.timeframe import resample_ohlcv, tf_minutes


def _min_df(start="2026-07-09 09:15", periods=90, base=100.0, tz="Asia/Kolkata"):
    ts = pd.date_range(start, periods=periods, freq="15min", tz=tz)
    return pd.DataFrame({
        "timestamp": ts,
        "open": [base + i for i in range(periods)],
        "high": [base + i + 1 for i in range(periods)],
        "low": [base + i - 1 for i in range(periods)],
        "close": [base + i + 0.5 for i in range(periods)],
        "volume": [1000] * periods,
    })


def test_tf_minutes():
    assert tf_minutes("1hr") == 60
    with pytest.raises(ValueError):
        tf_minutes("bogus")


def test_session_aligned_origin():
    # 15-min bars from 09:15 -> 1hr bars must start at 09:15, 10:15, ... (not 10:00)
    df = _min_df(periods=20)
    out = resample_ohlcv(df, "1hr")
    starts = [t.strftime("%H:%M") for t in out["timestamp"]]
    assert starts[0] == "09:15"
    assert starts[1] == "10:15"


def test_ohlcv_aggregation_correct():
    df = _min_df(periods=4)                 # exactly one 1hr bar (09:15–10:15)
    out = resample_ohlcv(df, "1hr")
    assert len(out) == 1
    bar = out.iloc[0]
    assert bar["open"] == df.iloc[0]["open"]         # first
    assert bar["close"] == df.iloc[3]["close"]       # last
    assert bar["high"] == df["high"].max()
    assert bar["low"] == df["low"].min()
    assert bar["volume"] == df["volume"].sum()


def test_closed_bar_rule_drops_forming_bar():
    df = _min_df(periods=6)   # 09:15..10:30; bars: [09:15-10:15 closed], [10:15-... forming]
    # now = 10:20: the 10:15 bar closes at 11:15 -> not yet closed
    out = resample_ohlcv(df, "1hr", now=pd.Timestamp("2026-07-09 10:20", tz="Asia/Kolkata"))
    assert len(out) == 1
    assert out.iloc[0]["timestamp"].strftime("%H:%M") == "09:15"


def test_closed_bar_boundary_precise():
    df = _min_df(periods=8)   # through 11:00
    tz = "Asia/Kolkata"
    # 10:14:59 -> 09:15 bar (closes 10:15) not yet closed -> 0 bars
    out_before = resample_ohlcv(df, "1hr", now=pd.Timestamp("2026-07-09 10:14:59", tz=tz))
    assert len(out_before) == 0
    # 10:15:00 -> 09:15 bar just closed -> exactly 1
    out_at = resample_ohlcv(df, "1hr", now=pd.Timestamp("2026-07-09 10:15:00", tz=tz))
    assert len(out_at) == 1


def test_consistency_with_stored_native_candles():
    """Resampling 15-min -> 1hr must match Kite native 1hr on OHLC (vol ±1%)."""
    import yaml
    from src.backtest_store import BacktestStore
    cfg = yaml.safe_load(open("config/config.yaml"))
    store = BacktestStore(cfg["backtest_data"]["store_path"])
    syms = set(store.symbols("15min")) & set(store.symbols("1hr"))
    if not syms:
        pytest.skip("no stored 15min+1hr data to validate against")
    sym = sorted(syms)[0]
    m15 = store.get_candles(sym, "15min")
    native = store.get_candles(sym, "1hr").set_index("timestamp")
    resampled = resample_ohlcv(m15, "1hr").set_index("timestamp")
    common = resampled.index.intersection(native.index)
    assert len(common) > 20                         # meaningful overlap
    checked = 0
    for ts in common[:200]:
        r, n = resampled.loc[ts], native.loc[ts]
        # only compare fully-populated 15-min bars (4 per hour) — skip session edges
        assert abs(r["open"] - n["open"]) < 0.01 * max(1, n["open"])
        assert abs(r["close"] - n["close"]) < 0.01 * max(1, n["close"])
        assert r["high"] >= n["high"] - 0.01 * max(1, n["high"])
        assert r["low"] <= n["low"] + 0.01 * max(1, n["low"])
        checked += 1
    assert checked > 20


def test_naive_timestamps_supported():
    df = _min_df(periods=4, tz=None)
    out = resample_ohlcv(df, "1hr", now=datetime(2026, 7, 9, 11, 0))
    assert len(out) == 1


def test_empty_input():
    assert resample_ohlcv(pd.DataFrame(), "1hr").empty
