"""indicators/levels.py — support & resistance, four tiers (spec section 15).

Preferred in order: (1) OBJECTIVE (prior day/week H/L/C, round numbers, 52w — zero
params, can't be curve-fit), (2) volume profile (existing module), (3) pivot clusters
(confirmed swing pivots clustered within cluster_tol_atr; >= touch_min touches = a
level), (4) fib (derived, indicators.fib).

Levels are ZONES, not lines: width = zone_atr x ATR; a 'touch' is a close/extreme
within the zone. Exact-price logic is noise. Detection is deterministic and inherits
the pivot confirmation lag (indicators.swings).
"""
from indicators.core import atr
from indicators.swings import swing_pivots


def make_zone(center: float, atr_val: float, zone_atr: float = 0.25) -> dict:
    half = zone_atr * atr_val
    return {"center": round(center, 4), "low": round(center - half, 4),
            "high": round(center + half, 4)}


def is_touch(price: float, zone: dict) -> bool:
    return zone["low"] <= price <= zone["high"]


def tier1_levels(df, as_of: int = None, round_step: int = 50) -> list:
    """Objective levels — zero parameters, can't be curve-fit (section 15.1)."""
    i = (len(df) - 1) if as_of is None else as_of
    if i < 1:
        return []
    out = [{"source": "pdh", "price": float(df["high"].iloc[i - 1])},
           {"source": "pdl", "price": float(df["low"].iloc[i - 1])},
           {"source": "pdc", "price": float(df["close"].iloc[i - 1])}]
    price = float(df["close"].iloc[i])
    out.append({"source": "round", "price": round(price / round_step) * round_step})
    if i >= 252:
        out.append({"source": "52w_high", "price": float(df["high"].iloc[i - 251:i + 1].max())})
        out.append({"source": "52w_low", "price": float(df["low"].iloc[i - 251:i + 1].min())})
    return out


def pivot_cluster_levels(df, swing_n: int = 10, cluster_tol_atr: float = 0.25,
                         touch_min: int = 2, zone_atr: float = 0.25,
                         as_of: int = None) -> list:
    """Tier-3: cluster confirmed swing pivots; a cluster with >= touch_min touches
    becomes a level with strength = touches x recency (section 15.3)."""
    i = (len(df) - 1) if as_of is None else as_of
    a = float(atr(df.iloc[:i + 1], 14).iloc[-1]) if i >= 15 else 0.0
    if a <= 0:
        return []
    highs, lows = swing_pivots(df, swing_n, as_of=i)
    pts = sorted([(p, v) for p, v in highs] + [(p, v) for p, v in lows], key=lambda t: t[1])
    tol = cluster_tol_atr * a
    clusters, cur = [], []
    for pos, price in pts:
        if cur and price - cur[-1][1] > tol:
            clusters.append(cur); cur = []
        cur.append((pos, price))
    if cur:
        clusters.append(cur)
    levels = []
    for cl in clusters:
        if len(cl) < touch_min:
            continue
        center = sum(v for _, v in cl) / len(cl)
        recency = 1.0 + (max(p for p, _ in cl) / max(i, 1))     # newer clusters stronger
        z = make_zone(center, a, zone_atr)
        levels.append({**z, "source": "pivot_cluster", "touches": len(cl),
                       "strength": round(len(cl) * recency, 3)})
    return levels
