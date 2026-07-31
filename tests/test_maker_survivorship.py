"""Strategy Maker — survivorship / newcomer-bias audit of the backtest universe."""
import pandas as pd

from maker.survivorship import audit_coverage, drop_partial_history


def _df(start, periods):
    ts = pd.date_range(start, periods=periods, freq="D", tz="Asia/Kolkata")
    return pd.DataFrame({"timestamp": ts, "open": 100.0, "high": 101.0,
                         "low": 99.0, "close": 100.0, "volume": 1000})


def test_flags_and_drops_partial_history_names():
    candles = {
        "FULL_A": _df("2024-01-01", 400),      # spans the whole window
        "FULL_B": _df("2024-01-05", 396),      # spans (well within tolerance)
        "NEWCOMER": _df("2025-06-01", 90),     # listed late -> partial history
    }
    rep = audit_coverage(candles)
    partial = {p["symbol"] for p in rep["partial"]}
    assert partial == {"NEWCOMER"}
    assert set(rep["covered"]) == {"FULL_A", "FULL_B"}
    assert rep["residual_bias"] and "survivorship" in rep["residual_bias"].lower()

    kept, rep2 = drop_partial_history(candles)
    assert set(kept) == {"FULL_A", "FULL_B"}   # newcomer removed from the search universe


def test_empty_universe_is_safe():
    rep = audit_coverage({})
    assert rep["covered"] == [] and rep["partial"] == [] and rep["coverage_frac"] == 0.0
