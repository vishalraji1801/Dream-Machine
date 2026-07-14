from src.tick_candle_builder import TickCandleBuilder


def test_ticks_in_same_bucket_form_one_bar():
    b = TickCandleBuilder(interval_seconds=300)
    b.add_tick("X", 100.0, 1000, 0)      # bucket 0
    b.add_tick("X", 102.0, 1500, 120)    # same 5-min bucket
    b.add_tick("X", 101.0, 1800, 240)
    df = b.get_candles("X")
    assert len(df) == 1
    row = df.iloc[0]
    assert row["open"] == 100.0
    assert row["high"] == 102.0
    assert row["low"] == 100.0
    assert row["close"] == 101.0
    assert row["volume"] == 800   # 1800 cumulative - 1000 first


def test_new_bucket_opens_new_bar():
    b = TickCandleBuilder(interval_seconds=300)
    b.add_tick("X", 100.0, 1000, 0)
    b.add_tick("X", 105.0, 2000, 301)    # next bucket
    df = b.get_candles("X")
    assert len(df) == 2
    assert df.iloc[1]["open"] == 105.0


def test_per_symbol_isolation():
    b = TickCandleBuilder()
    b.add_tick("A", 10.0, 100, 0)
    b.add_tick("B", 20.0, 200, 0)
    assert set(b.symbols()) == {"A", "B"}
    assert b.get_candles("A").iloc[0]["open"] == 10.0
    assert b.get_candles("B").iloc[0]["open"] == 20.0


def test_max_bars_capped():
    b = TickCandleBuilder(interval_seconds=60, max_bars=3)
    for i in range(6):
        b.add_tick("X", 100.0 + i, 100 * (i + 1), i * 60)  # each in a new bucket
    df = b.get_candles("X")
    assert len(df) == 3  # oldest dropped


def test_unknown_symbol_returns_none():
    assert TickCandleBuilder().get_candles("NOPE") is None


# ── SCRUM-106: seeding + tick continuation ────────────────────────────────────

import pandas as pd


def _rest_df(times_ist, base=100.0):
    return pd.DataFrame({
        "timestamp": [pd.Timestamp(t, tz="Asia/Kolkata") for t in times_ist],
        "open": [base] * len(times_ist), "high": [base + 1] * len(times_ist),
        "low": [base - 1] * len(times_ist), "close": [base + 0.5] * len(times_ist),
        "volume": [1000.0] * len(times_ist),
    })


def test_seed_preserves_bars_and_volume():
    b = TickCandleBuilder(interval_seconds=900)
    n = b.seed("X", _rest_df(["2026-07-09 09:15", "2026-07-09 09:30"]))
    assert n == 2
    df = b.get_candles("X")
    assert len(df) == 2
    assert df.iloc[0]["volume"] == 1000.0          # fetched volume kept as-is
    assert str(df.iloc[0]["timestamp"].tz) == "Asia/Kolkata"


def test_seed_drops_forming_bucket():
    b = TickCandleBuilder(interval_seconds=900)
    bars = _rest_df(["2026-07-09 09:15", "2026-07-09 09:30", "2026-07-09 09:45"])
    now = pd.Timestamp("2026-07-09 09:50", tz="Asia/Kolkata").timestamp()  # 09:45 bar forming
    n = b.seed("X", bars, now_epoch=now)
    assert n == 2                                   # 09:45 dropped — ticks own it


def test_ticks_continue_seeded_series():
    b = TickCandleBuilder(interval_seconds=900)
    now = pd.Timestamp("2026-07-09 09:50", tz="Asia/Kolkata").timestamp()
    b.seed("X", _rest_df(["2026-07-09 09:15", "2026-07-09 09:30"]), now_epoch=now)
    b.add_tick("X", 101.0, 500000, now)             # forming 09:45 bar from ticks
    b.add_tick("X", 102.0, 505000, now + 60)
    df = b.get_candles("X")
    assert len(df) == 3
    last = df.iloc[-1]
    assert last["high"] == 102.0
    assert last["volume"] == 5000.0                 # cumulative delta within bar
    assert df["timestamp"].is_monotonic_increasing  # merged in order, same tz


def test_reads_are_thread_safe_shape():
    # sanity: concurrent-ish read during writes doesn't corrupt bar dicts
    b = TickCandleBuilder(interval_seconds=60)
    for i in range(50):
        b.add_tick("X", 100.0 + i, 1000.0 * i, i * 60)
        assert b.bar_count("X") == min(i + 1, 120)
    assert len(b.get_candles("X")) == 50
