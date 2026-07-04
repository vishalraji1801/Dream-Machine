"""
Intraday scanner (V2 P3).

Ranks the streamed universe every cycle and hands the strategy engine a shortlist
of the most active names, so the watchlist becomes a function of the market
instead of a fixed constant. All inputs are computable from a single quote
snapshot (ltp, day open, day high/low, prev close, cumulative volume).

The score favours names with directional energy and room to run — the first-cut
'something is happening here' signal. True 20-day RVOL needs the universe
builder to supply average volume; that refinement is left to a later pass.
"""
from typing import Optional

from src.logger import get_logger

logger = get_logger("scanner")


def score_quote(q: dict, cfg: dict) -> Optional[dict]:
    """Score one symbol's quote. Returns a dict with score + components, or None."""
    ltp = q.get("ltp")
    prev_close = q.get("close")
    high = q.get("high")
    low = q.get("low")
    if not ltp or not prev_close:
        return None

    pct_change = (ltp - prev_close) / prev_close * 100
    gap = ((q.get("open", ltp) - prev_close) / prev_close * 100) if prev_close else 0.0

    # range position: 1.0 = at day high (breakout fuel), 0.0 = at day low
    rng = (high - low) if (high and low and high > low) else 0.0
    range_pos = ((ltp - low) / rng) if rng else 0.5
    # distance of ltp from the extreme it is closest to (0..0.5 -> proximity)
    extreme_proximity = max(range_pos, 1 - range_pos)

    w = cfg.get("scanner", {})
    score = (
        abs(pct_change) * w.get("w_pct_change", 1.0)
        + extreme_proximity * w.get("w_range_pos", 2.0)
        + abs(gap) * w.get("w_gap", 0.5)
    )
    return {
        "symbol": q.get("symbol"),
        "score": round(score, 4),
        "pct_change": round(pct_change, 3),
        "rvol": None,  # requires avg-volume from the universe builder (future)
    }


def rank(quotes: dict[str, dict], cfg: dict) -> list[dict]:
    """
    quotes: {symbol: quote_dict} (quote must include its own 'symbol' or the key
    is used). Returns the top-N ranked candidates for this cycle.
    """
    top_n = cfg.get("scanner", {}).get("top_n", 30)
    scored = []
    for symbol, q in quotes.items():
        q = {**q, "symbol": q.get("symbol", symbol)}
        s = score_quote(q, cfg)
        if s:
            scored.append(s)
    scored.sort(key=lambda x: x["score"], reverse=True)
    for i, s in enumerate(scored, 1):
        s["rank"] = i
    return scored[:top_n]
