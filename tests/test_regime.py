"""Regime classifier (commit 1) — determinism, hysteresis, no look-ahead, purity."""
import pandas as pd
import pytest

from src.market_state import MarketState, compute_market_state
from src.regime import Regime, RegimeConfig, RegimeState, classify


def ms(**kw) -> MarketState:
    base = dict(close=100.0, ema_fast=100.0, ema_slow=100.0, ema_slope=0.0,
                adx=10.0, atr=0.5, atr_pct=0.5, bb_width=0.1, bb_width_pctile=0.5,
                breadth=None, n_bars=100, config_version="t")
    base.update(kw)
    return MarketState(**base)


CFG = RegimeConfig()


# ── test 1: classifier determinism ────────────────────────────────────────────

def test_strong_trend_up_exact():
    r = classify(ms(adx=35, close=110, ema_slow=100, ema_slope=0.01), None, CFG)
    assert r.regime is Regime.STRONG_TREND_UP
    assert r.confidence == pytest.approx((35 - 25) / 25)   # 0.4


def test_strong_trend_down():
    r = classify(ms(adx=40, close=90, ema_slow=100, ema_slope=-0.01), None, CFG)
    assert r.regime is Regime.STRONG_TREND_DOWN


def test_high_vol_chop():
    r = classify(ms(adx=12, atr_pct=1.5), None, CFG)
    assert r.regime is Regime.HIGH_VOL_CHOP
    assert r.confidence == pytest.approx((1.5 - 1.0) / 1.0)   # 0.5


def test_quiet():
    r = classify(ms(adx=10, atr_pct=0.2, bb_width_pctile=0.1), None, CFG)
    assert r.regime is Regime.QUIET


def test_range():
    r = classify(ms(adx=10, atr_pct=0.6), None, CFG)
    assert r.regime is Regime.RANGE
    assert r.confidence == pytest.approx((20 - 10) / 20)   # 0.5


def test_unknown_on_insufficient_bars():
    r = classify(ms(adx=35, close=110, ema_slow=100, ema_slope=0.01, n_bars=10), None, CFG)
    assert r.regime is Regime.UNKNOWN
    assert r.confidence == 0.0


# ── test 2: hysteresis / dwell ────────────────────────────────────────────────

def test_one_bar_blip_does_not_switch():
    cfg = RegimeConfig(min_dwell_bars=3)
    up = ms(adx=35, close=110, ema_slow=100, ema_slope=0.01)
    rng = ms(adx=10, atr_pct=0.6)
    committed = classify(up, None, cfg)
    assert committed.regime is Regime.STRONG_TREND_UP

    blip = classify(rng, committed, cfg)             # one differing bar
    assert blip.regime is Regime.STRONG_TREND_UP     # held
    assert blip.pending_regime is Regime.RANGE and blip.pending_bars == 1

    recovered = classify(up, blip, cfg)              # candidate abandoned
    assert recovered.regime is Regime.STRONG_TREND_UP
    assert recovered.pending_bars == 0


def test_sustained_change_switches_after_dwell():
    cfg = RegimeConfig(min_dwell_bars=3)
    up = ms(adx=35, close=110, ema_slow=100, ema_slope=0.01)
    rng = ms(adx=10, atr_pct=0.6)
    committed = classify(up, None, cfg)
    a = classify(rng, committed, cfg)   # pending 1
    b = classify(rng, a, cfg)           # pending 2
    c = classify(rng, b, cfg)           # pending 3 -> commit
    assert a.regime is Regime.STRONG_TREND_UP
    assert b.regime is Regime.STRONG_TREND_UP
    assert c.regime is Regime.RANGE
    assert c.since_bars == 1


# ── test 3: no look-ahead (compute + classify pipeline) ───────────────────────

def _range_df(n=70):
    rows = []
    for i in range(n):
        c = 100 + (0.5 if i % 2 else -0.5)      # tiny oscillation -> non-trending
        rows.append({"open": c, "high": c + 0.4, "low": c - 0.4, "close": c,
                     "volume": 100_000})
    return pd.DataFrame(rows)


def test_classify_as_of_t_ignores_next_bar():
    df = _range_df(70)
    spike = {"open": 100, "high": 106, "low": 97, "close": 101, "volume": 500_000}
    df_next = pd.concat([df, pd.DataFrame([spike])], ignore_index=True)

    ms_t = compute_market_state(df, {"ms_ema_slow": 30})
    ms_t1 = compute_market_state(df_next, {"ms_ema_slow": 30})

    # the appended bar genuinely raises volatility (so it *would* change the label)
    assert ms_t1.atr_pct > ms_t.atr_pct * 1.2

    # thresholds derived from the data so both stay non-trending and only the
    # spike bar crosses the high-vol line
    cfg = RegimeConfig(atr_pct_high=(ms_t.atr_pct + ms_t1.atr_pct) / 2,
                       atr_pct_low=ms_t.atr_pct / 2,
                       adx_range=max(ms_t.adx, ms_t1.adx) + 5,
                       adx_trend=max(ms_t.adx, ms_t1.adx) + 10,
                       min_bars=40)
    r_t = classify(ms_t, None, cfg)
    r_t1 = classify(ms_t1, None, cfg)
    assert r_t.regime is Regime.RANGE            # as-of-t label, no peek at t+1
    assert r_t1.regime is Regime.HIGH_VOL_CHOP   # only changes once t+1 is included
    assert r_t.regime != r_t1.regime


# ── purity guard ──────────────────────────────────────────────────────────────

def test_regime_and_market_state_are_pure():
    import src.market_state as msmod
    import src.regime as rmod
    for mod in (msmod, rmod):
        src = open(mod.__file__, encoding="utf-8").read()
        assert "datetime.now(" not in src
        assert "kiteconnect" not in src
        assert "\nopen(" not in src and " open(" not in src.replace("open=", "")
