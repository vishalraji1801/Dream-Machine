"""Pinned indicators — golden-fixture test (Strategy Maker, spec section 13, test 20).

Fixed candle fixture -> exact values, asserted to 6dp, forever. A smoothing change is a
breaking change (that is the point).
"""
import math

import pandas as pd

from indicators import core as I


def _fixture(n=60):
    close = [100 + 5 * math.sin(i / 5) + i * 0.2 for i in range(n)]
    return pd.DataFrame({"open": close, "high": [c + 1 for c in close],
                         "low": [c - 1 for c in close], "close": close,
                         "volume": [1000 + i for i in range(n)]})


def _last(x):
    return round(float(x), 6)


def test_golden_values():
    df = _fixture()
    s = df["close"]
    assert _last(I.sma(s, 20).iloc[-1]) == 108.858174
    assert _last(I.ema(s, 20).iloc[-1]) == 107.715558
    assert _last(I.rsi(df, 14).iloc[-1]) == 56.402649          # Wilder
    assert _last(I.atr(df, 14).iloc[-1]) == 2.008541           # Wilder
    assert _last(I.atr_pct(df, 14).iloc[-1]) == 1.854054
    assert _last(I.adx(df, 14).iloc[-1]) == 29.337436          # Wilder
    macd = I.macd(s).iloc[-1]
    assert (_last(macd["macd"]), _last(macd["signal"]), _last(macd["hist"])) == \
           (-0.134968, 0.167117, -0.302085)
    boll = I.bollinger(s).iloc[-1]
    assert (_last(boll["upper"]), _last(boll["lower"])) == (114.043655, 103.672693)
    assert _last(I.bb_width_pctile(s, 20, 30).iloc[-1]) == 30.0
    don = I.donchian(df, 10).iloc[-1]
    assert (_last(don["upper"]), _last(don["lower"])) == (109.332375, 104.895319)
    st = I.stochastic(df).iloc[-1]
    assert (_last(st["k"]), _last(st["d"])) == (53.543944, 38.022868)


def test_wilder_rsi_bounds():
    df = _fixture()
    r = I.rsi(df, 14).dropna()
    assert (r >= 0).all() and (r <= 100).all()


def test_indicators_are_tf_agnostic():
    # same math on any frame handed in — no hidden timeframe assumption
    df = _fixture(120)
    assert len(I.atr(df, 14)) == 120
    assert not math.isnan(float(I.adx(df, 14).iloc[-1]))
