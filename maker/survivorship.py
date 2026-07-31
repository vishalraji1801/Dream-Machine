"""maker/survivorship.py — survivorship / newcomer-bias audit for the backtest universe.

Certification runs on TODAY's liquid F&O universe. Two distinct biases follow:

  1. NEWCOMER bias (detectable, fixable here): a name that listed partway through the
     backtest window has data for only part of the span. Including it lets the search
     cherry-pick a name that only existed during a favourable stretch. We DETECT these by
     coverage and can DROP them so every certified edge is measured on names present for
     the whole window.

  2. TRUE SURVIVORSHIP bias (NOT fixable here — disclosed, never silently ignored): names
     that DELISTED or fell out of the index are absent from today's universe entirely, so
     their failures never enter the backtest. Removing this needs point-in-time index
     constituents (historical membership), which this project does not have. The honest
     mitigation is disclosure + treating certified PF as biased HIGH by an unknown margin.

This module makes both explicit instead of hiding them inside a clean-looking backtest.
"""
import pandas as pd


def audit_coverage(candles: dict, min_coverage_frac: float = 0.90) -> dict:
    """Report each symbol's history coverage over the universe window [min_start, max_end].

    A symbol whose bars cover < min_coverage_frac of that window is flagged `partial`
    (likely a newcomer / recent listing). Returns:
      {window: (start, end), covered: [sym...], partial: [{symbol, first_bar, coverage}],
       coverage_frac: float, residual_bias: str}
    """
    spans = {}
    for s, df in candles.items():
        if df is None or len(df) == 0:
            continue
        ts = pd.to_datetime(df["timestamp"])
        spans[s] = (ts.min(), ts.max())
    if not spans:
        return {"window": (None, None), "covered": [], "partial": [],
                "coverage_frac": 0.0, "residual_bias": _RESIDUAL}

    win_start = min(v[0] for v in spans.values())
    win_end = max(v[1] for v in spans.values())
    total = (win_end - win_start).days or 1

    covered, partial = [], []
    for s, (start, end) in sorted(spans.items()):
        cov = (end - start).days / total
        if start <= win_start + pd.Timedelta(days=total * (1 - min_coverage_frac)):
            covered.append(s)
        else:
            partial.append({"symbol": s, "first_bar": start.date().isoformat(),
                            "coverage": round(cov, 3)})
    return {"window": (win_start.date().isoformat(), win_end.date().isoformat()),
            "covered": covered, "partial": partial,
            "coverage_frac": round(len(covered) / len(spans), 3),
            "residual_bias": _RESIDUAL}


def drop_partial_history(candles: dict, min_coverage_frac: float = 0.90) -> tuple[dict, dict]:
    """Return (kept_candles, audit_report) with newcomer / partial-history names removed so
    the search sees only names present for the whole window. Never touches the true-
    survivorship residual (unfixable) — that stays in the report for disclosure."""
    report = audit_coverage(candles, min_coverage_frac)
    drop = {p["symbol"] for p in report["partial"]}
    kept = {s: df for s, df in candles.items() if s not in drop}
    return kept, report


_RESIDUAL = ("TRUE survivorship bias (delisted / index-dropped names absent from the "
             "universe) is NOT corrected — needs point-in-time constituents. Treat certified "
             "PF as biased HIGH by an unknown margin.")
