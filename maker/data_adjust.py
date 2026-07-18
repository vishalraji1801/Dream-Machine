"""maker/data_adjust.py — corporate-action adjustment (Strategy Maker, spec section 12.2).

CRITICAL: Kite DAILY candles are split/bonus-adjusted; INTRADAY candles are NOT.
Unpatched, any strategy spanning a split date trades a phantom gap. We keep an
adjustment-factor table per symbol and apply it to the 1-min store on load, then a
reconciliation test asserts daily derived from adjusted 1-min matches native daily.

A corporate action is (ex_date, ratio): a 2:1 split is ratio 2.0 (price halves, volume
doubles from the ex_date on). Prices BEFORE an ex_date are divided by the cumulative
product of ratios on/after that date (back-adjustment, matching Kite's daily series).
"""
import pandas as pd


def cumulative_divisor(date, actions) -> float:
    """Price divisor for a bar dated `date`: product of ratios of all actions whose
    ex_date is strictly after `date` (those adjustments have not yet 'happened')."""
    d = pd.to_datetime(date)
    div = 1.0
    for ex_date, ratio in actions:
        if d < pd.to_datetime(ex_date):
            div *= ratio
    return div


def adjust_1min(df: pd.DataFrame, actions) -> pd.DataFrame:
    """Back-adjust a raw 1-min frame for splits/bonuses so it aligns with Kite daily."""
    if not actions:
        return df.copy()
    out = df.copy()
    ts = pd.to_datetime(out["timestamp"])
    div = ts.dt.normalize().map(lambda d: cumulative_divisor(d, actions))
    for col in ("open", "high", "low", "close"):
        out[col] = out[col] / div
    out["volume"] = out["volume"] * div
    return out


def resample_daily_from_1min(df: pd.DataFrame) -> pd.DataFrame:
    """Daily OHLCV from 1-min (closed bars). Grouped by trading date."""
    d = df.copy()
    d["timestamp"] = pd.to_datetime(d["timestamp"])
    g = d.groupby(d["timestamp"].dt.normalize())
    out = pd.DataFrame({
        "open": g["open"].first(), "high": g["high"].max(),
        "low": g["low"].min(), "close": g["close"].last(),
        "volume": g["volume"].sum()}).reset_index(names="timestamp")
    return out


def reconcile(adjusted_1min: pd.DataFrame, native_daily: pd.DataFrame,
              tol: float = 0.01) -> bool:
    """Daily derived from adjusted 1-min must match native daily OHLC within tol (%).
    Returns True if every overlapping day matches; the campaign blocks otherwise."""
    derived = resample_daily_from_1min(adjusted_1min).set_index(
        pd.to_datetime(resample_daily_from_1min(adjusted_1min)["timestamp"]).dt.normalize())
    nat = native_daily.copy()
    nat.index = pd.to_datetime(nat["timestamp"]).dt.normalize()
    common = derived.index.intersection(nat.index)
    if len(common) == 0:
        return False
    for col in ("open", "high", "low", "close"):
        a, b = derived.loc[common, col], nat.loc[common, col]
        rel = ((a - b).abs() / b.abs().replace(0, 1e-9)) * 100
        if (rel > tol).any():
            return False
    return True
