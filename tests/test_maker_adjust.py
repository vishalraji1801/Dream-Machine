"""Strategy Maker — Commit 16: corporate-action adjustment + reconciliation (test 17)."""
import pandas as pd

from maker.data_adjust import adjust_1min, cumulative_divisor, reconcile, resample_daily_from_1min


def _one_min_with_split():
    """Raw 1-min around a 2:1 split on 2022-06-02: ~100 before, ~50 after (economically
    continuous). Native Kite daily is back-adjusted to ~50 throughout."""
    rows = []
    for day, base in [("2022-06-01", 100.0), ("2022-06-02", 50.0), ("2022-06-03", 50.5)]:
        for m in range(3):
            t = pd.Timestamp(f"{day} 09:{15+m}:00")
            rows.append({"timestamp": t, "open": base, "high": base + 1,
                         "low": base - 1, "close": base + 0.5, "volume": 1000})
    return pd.DataFrame(rows)


def _native_daily():
    # Kite daily = back-adjusted: day-1 (pre-split) OHLC halved; days 2-3 raw.
    return pd.DataFrame([
        {"timestamp": pd.Timestamp("2022-06-01"), "open": 50.0, "high": 50.5,
         "low": 49.5, "close": 50.25, "volume": 2000},
        {"timestamp": pd.Timestamp("2022-06-02"), "open": 50.0, "high": 51.0,
         "low": 49.0, "close": 50.5, "volume": 1000},
        {"timestamp": pd.Timestamp("2022-06-03"), "open": 50.5, "high": 51.5,
         "low": 49.5, "close": 51.0, "volume": 1000}])


ACTIONS = [("2022-06-02", 2.0)]           # 2:1 split


def test_cumulative_divisor():
    assert cumulative_divisor("2022-06-01", ACTIONS) == 2.0     # before split -> /2
    assert cumulative_divisor("2022-06-02", ACTIONS) == 1.0     # on/after -> raw
    assert cumulative_divisor("2022-06-03", ACTIONS) == 1.0


def test_unadjusted_1min_fails_reconciliation():
    raw = _one_min_with_split()
    assert reconcile(raw, _native_daily()) is False             # phantom split gap


def test_adjusted_1min_reconciles_with_native_daily():          # test 17
    adjusted = adjust_1min(_one_min_with_split(), ACTIONS)
    assert reconcile(adjusted, _native_daily()) is True
    # the pre-split 1-min prices were halved to match the back-adjusted daily
    pre = adjusted[pd.to_datetime(adjusted["timestamp"]).dt.normalize() == pd.Timestamp("2022-06-01")]
    assert abs(pre["close"].iloc[0] - 50.25) < 1e-6
