"""Strategy Maker — Commit 2: grammar, compile(), determinism (tests 1 + 9)."""
import pathlib

import pandas as pd
import pytest

from maker.grammar import Candidate, compile, make_candidate


def _uptrend(n=260):
    close = [100 + i * 0.5 for i in range(n)]
    return pd.DataFrame({
        "timestamp": pd.date_range("2020-01-01", periods=n, freq="D"),
        "open": close, "high": [c + 1 for c in close], "low": [c - 1 for c in close],
        "close": close, "volume": [100000] * n,
    })


def _donchian_like(**over):
    blocks = {
        "regime": ("trend_side", {"ma": 200, "side": "above"}),
        "setup": ("nday_extreme", {"lookback": 100, "side": "high"}),
        "trigger": ("breakout_close", {"of": "setup_level"}),
        "exit": ("atr_trail", {"mult": 5, "period": 14}),
    }
    blocks.update(over)
    return make_candidate("long", blocks)


def test_cid_is_stable_and_sensitive():
    a = _donchian_like()
    b = _donchian_like()
    assert a.cid == b.cid                                   # same choice -> same id
    c = _donchian_like(exit=("atr_trail", {"mult": 6, "period": 14}))
    assert c.cid != a.cid                                   # changed param -> new id


def test_condition_and_param_counts():
    a = _donchian_like()
    assert a.n_conditions == 3                              # regime + setup + trigger
    assert a.n_params == 2 + 2 + 1 + 2                      # ma/side, lookback/side, of, mult/period


def test_params_validated_against_grid():
    with pytest.raises(ValueError):
        make_candidate("long", {"setup": ("nday_extreme", {"lookback": 999, "side": "high"}),
                                "trigger": ("breakout_close", {"of": "setup_level"}),
                                "exit": ("r_multiple", {"r": 2})})


def test_compile_produces_a_buy_on_new_high():
    fn = compile(_donchian_like())
    sig = fn("X", _uptrend(), {})
    assert sig.direction == "BUY"
    assert sig.stop_loss < sig.entry_price < sig.target
    assert sig.reason.startswith("maker:")


def test_determinism_same_cid_same_data(  ):
    cand = _donchian_like()
    df = _uptrend()
    f1, f2 = compile(cand), compile(cand)
    s1, s2 = f1("X", df, {}), f2("X", df, {})
    assert (s1.direction, s1.entry_price, s1.stop_loss, s1.target) == \
           (s2.direction, s2.entry_price, s2.stop_loss, s2.target)
    assert f1.cid == f2.cid == cand.cid


def test_compiled_fn_is_pure_no_io_or_clock():
    src = (pathlib.Path("maker/grammar.py").read_text()
           + pathlib.Path("maker/blocks.py").read_text())
    for forbidden in ("import requests", "kiteconnect", "datetime.now(", "urllib", "socket."):
        assert forbidden not in src, f"grammar must be pure: found {forbidden!r}"
