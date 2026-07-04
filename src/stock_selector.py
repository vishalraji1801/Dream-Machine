"""
Liquid stock selector (SCRUM-98).

The old backtest selection was "the first N NSE equities in the price band" —
essentially unfiltered, so it could pick illiquid names with no tradeable edge.
This applies standard quality filters:

  1. Candidate pool  — a curated liquid list (universe.fno_underlyings) or, by
                       default, the NIFTY-50 watchlist (all large, liquid names).
  2. Liquidity floor — 20-day average daily turnover (avg close x avg volume)
                       must exceed min_turnover_cr.
  3. Volatility band — daily ATR as a % of price in [atr_pct_min, atr_pct_max]:
                       enough movement to clear costs, not so much a 1x stop is noise.
  4. Price band      — avg close within [price_min, price_max].

Candidates are then ranked by turnover (most liquid first) and the top N kept.
Only ~30 days of DAILY candles per candidate are needed (one cheap request each).
"""
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

from src.logger import get_logger
from src.strategy import _atr

logger = get_logger("stock_selector")


def daily_metrics(df: pd.DataFrame) -> dict:
    """Liquidity/volatility metrics from a symbol's recent DAILY candles."""
    close, vol = df["close"], df["volume"]
    avg_close = float(close.mean())
    avg_vol = float(vol.mean())
    atr = _atr(df, min(14, max(2, len(df) - 1)))
    return {
        "avg_close": round(avg_close, 2),
        "avg_volume": round(avg_vol, 0),
        "avg_turnover": avg_close * avg_vol,          # rupees/day
        "atr_pct": round(atr / avg_close * 100, 2) if avg_close else 0.0,
    }


def rank_candidates(metrics_by_symbol: dict, cfg: dict) -> list[str]:
    """Apply the quality filters and return symbols ranked by turnover (desc)."""
    u = cfg.get("universe", {})
    min_turnover = u.get("min_turnover_cr", 50) * 1e7   # crore -> rupees
    atr_lo = u.get("atr_pct_min", 1.0)
    atr_hi = u.get("atr_pct_max", 5.0)
    p_min = u.get("price_min", 100)
    p_max = u.get("price_max", 5000)

    passed = []
    for sym, m in metrics_by_symbol.items():
        if not (p_min <= m["avg_close"] <= p_max):
            continue
        if m["avg_turnover"] < min_turnover:
            continue
        if not (atr_lo <= m["atr_pct"] <= atr_hi):
            continue
        passed.append((sym, m))
    passed.sort(key=lambda x: x[1]["avg_turnover"], reverse=True)
    return [sym for sym, _ in passed]


def _default_daily_fetch(kite, token: int, days: int) -> Optional[pd.DataFrame]:
    to = datetime.now()
    frm = to - timedelta(days=days)
    raw = kite.historical_data(token, frm, to, "day")
    if not raw:
        return None
    return pd.DataFrame(raw).rename(columns={"date": "timestamp"})


def select_stocks(kite, cfg: dict, num_stocks: int, daily_fetch=None) -> list[dict]:
    """
    Return [{symbol, token}] for the top `num_stocks` liquid, adequately-volatile
    names from the candidate pool. `daily_fetch(kite, token, days)` is injectable
    for testing.
    """
    daily_fetch = daily_fetch or _default_daily_fetch
    u = cfg.get("universe", {})
    candidates = u.get("fno_underlyings") or cfg["trading"]["watchlist"]
    lookback = u.get("selection_lookback_days", 30)

    instruments = kite.instruments(cfg["trading"]["exchange"])
    token_of = {i["tradingsymbol"]: i["instrument_token"]
                for i in instruments if i.get("instrument_type") == "EQ"}

    metrics, tokens = {}, {}
    for sym in candidates:
        tok = token_of.get(sym)
        if tok is None:
            continue
        df = daily_fetch(kite, tok, lookback)
        if df is None or len(df) < 15:
            continue
        metrics[sym] = daily_metrics(df)
        tokens[sym] = tok

    ranked = rank_candidates(metrics, cfg)[:num_stocks]
    logger.info(f"Selected {len(ranked)} liquid stocks from {len(candidates)} candidates "
                f"(filtered on turnover, ATR%, price)")
    return [{"symbol": s, "token": tokens[s]} for s in ranked]
