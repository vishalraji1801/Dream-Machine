"""Strategy Maker — Commit 21: indicator cache + span-hash (test 23)."""
from maker.cache import IndicatorCache, span_hash


def test_cache_computes_once_and_returns_identical():
    cache = IndicatorCache()
    calls = {"n": 0}

    def compute():
        calls["n"] += 1
        return [1, 2, 3]

    sp = span_hash("RELIANCE", "1d", "2016", "2024", "screen")
    a = cache.get_or_compute("RELIANCE", "1d", "rsi", {"period": 14}, sp, compute)
    b = cache.get_or_compute("RELIANCE", "1d", "rsi", {"period": 14}, sp, compute)
    assert a == b == [1, 2, 3]
    assert calls["n"] == 1 and cache.computes == 1        # computed once, reused


def test_cached_equals_uncached():
    cache = IndicatorCache()
    sp = span_hash("X", "1d", "a", "b", "screen")
    uncached = sorted([3, 1, 2])
    cached = cache.get_or_compute("X", "1d", "sma", {"n": 20}, sp, lambda: sorted([3, 1, 2]))
    assert cached == uncached


def test_screen_and_reserve_keyspaces_are_disjoint():
    screen_sp = span_hash("X", "1d", "2016", "2022", "screen")
    reserve_sp = span_hash("X", "1d", "2022", "2024", "reserve")
    assert screen_sp != reserve_sp

    cache = IndicatorCache()
    cache.get_or_compute("X", "1d", "atr", {"period": 14}, screen_sp, lambda: [1])
    # a screen-stage run only ever used the screen span; no reserve key present
    assert cache.spans_used() == {screen_sp}
    assert reserve_sp not in cache.spans_used()


def test_span_hash_changes_with_stage():
    assert span_hash("X", "1d", "a", "b", "screen") != span_hash("X", "1d", "a", "b", "reserve")
    assert span_hash("X", "1d", "a", "b", "screen") == span_hash("X", "1d", "a", "b", "screen")
