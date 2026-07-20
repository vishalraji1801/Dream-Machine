"""indicators/core.py — pinned indicator math (Strategy Maker, spec section 13).

All functions take a price series or an OHLCV frame and return a pandas Series/scalar.
Wilder smoothing = ewm(alpha=1/period, adjust=False). No third-party TA library.
"""
import pandas as pd


def sma(series: pd.Series, n: int) -> pd.Series:
    return series.rolling(n).mean()


def ema(series: pd.Series, n: int) -> pd.Series:
    return series.ewm(span=n, adjust=False).mean()


def _wilder(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(alpha=1.0 / period, adjust=False).mean()


def rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder RSI."""
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = _wilder(gain, period)
    avg_loss = _wilder(loss, period)
    rs = avg_gain / avg_loss.replace(0, 1e-12)
    return 100 - 100 / (1 + rs)


def _true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    return pd.concat([df["high"] - df["low"],
                      (df["high"] - prev_close).abs(),
                      (df["low"] - prev_close).abs()], axis=1).max(axis=1)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder ATR."""
    return _wilder(_true_range(df), period)


def atr_pct(df: pd.DataFrame, period: int = 14) -> pd.Series:
    return atr(df, period) / df["close"] * 100


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder ADX (directional movement index)."""
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = ((up > down) & (up > 0)) * up
    minus_dm = ((down > up) & (down > 0)) * down
    tr = _wilder(_true_range(df), period)
    plus_di = 100 * _wilder(plus_dm, period) / tr.replace(0, 1e-12)
    minus_di = 100 * _wilder(minus_dm, period) / tr.replace(0, 1e-12)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-12)
    return _wilder(dx, period)


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(series, fast) - ema(series, slow)
    sig = line.ewm(span=signal, adjust=False).mean()
    return pd.DataFrame({"macd": line, "signal": sig, "hist": line - sig})


def bollinger(series: pd.Series, period: int = 20, sd: float = 2.0) -> pd.DataFrame:
    mid = series.rolling(period).mean()
    std = series.rolling(period).std()          # sample std (ddof=1)
    return pd.DataFrame({"mid": mid, "upper": mid + sd * std, "lower": mid - sd * std})


def bb_width_pctile(series: pd.Series, period: int = 20, lookback: int = 100) -> pd.Series:
    mid = series.rolling(period).mean()
    width = series.rolling(period).std() / mid
    return width.rolling(lookback).apply(lambda w: (w < w.iloc[-1]).mean() * 100, raw=False)


def donchian(df: pd.DataFrame, n: int) -> pd.DataFrame:
    return pd.DataFrame({"upper": df["high"].rolling(n).max(),
                         "lower": df["low"].rolling(n).min()})


def stochastic(df: pd.DataFrame, k: int = 14, d: int = 3) -> pd.DataFrame:
    low_k = df["low"].rolling(k).min()
    high_k = df["high"].rolling(k).max()
    pct_k = 100 * (df["close"] - low_k) / (high_k - low_k).replace(0, 1e-12)
    return pd.DataFrame({"k": pct_k, "d": pct_k.rolling(d).mean()})
