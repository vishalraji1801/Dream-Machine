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
