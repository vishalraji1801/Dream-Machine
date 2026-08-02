"""maker/permute.py - Monte-Carlo permutation test (Strategy Maker).

Walk-forward OOS answers "does the edge survive on unseen data?"; a permutation test answers
a DIFFERENT question that walk-forward misses at large search N: "is this edge distinguishable
from what a strategy of the same shape would earn on data with NO exploitable serial structure?"
It is the standard defense against data-mining bias.

Scheme (Masters bar decomposition): for each symbol, decompose every bar into log factors
relative to the prior close / this bar's open - the gap (open/prev_close) and the intrabar
open->high, open->low, open->close moves. Shuffle the SEQUENCE of those factor tuples and
rebuild a synthetic OHLC series. This preserves the marginal distribution of single-bar moves
and intrabar ranges but destroys the serial dependence (trends, levels, patterns) a real edge
exploits. Re-run the candidate on many such permutations:

    p = (1 + #{permutation net >= observed net}) / (n_perms + 1)

A low p means the observed edge is unlikely under the "no structure" null -> real. This module
is REPORT-ONLY for now (records p; does not gate) - promote to a hard reserve gate once the
p-value distribution across a campaign is calibrated.
"""
import random

import numpy as np
import pandas as pd

from maker.screen import WINDOW, _prepare_cfg


def _net(res) -> float:
    return float(res.net_pnl)


def permute_ohlc(df: pd.DataFrame, rng: random.Random) -> pd.DataFrame:
    """One permutation of a symbol's OHLC via the bar-decomposition shuffle (above).
    timestamp + volume are preserved in place; only the price path is permuted."""
    n = len(df)
    if n < 3:
        return df.copy()
    o = df["open"].to_numpy(float);  c = df["close"].to_numpy(float)
    h = df["high"].to_numpy(float);  l = df["low"].to_numpy(float)
    eps = 1e-9
    log_gap = np.log(np.maximum(o[1:], eps) / np.maximum(c[:-1], eps))
    log_hi = np.log(np.maximum(h[1:], eps) / np.maximum(o[1:], eps))
    log_lo = np.log(np.maximum(l[1:], eps) / np.maximum(o[1:], eps))
    log_cl = np.log(np.maximum(c[1:], eps) / np.maximum(o[1:], eps))
    perm = list(range(n - 1))
    rng.shuffle(perm)
    g, hi, lo, cl = log_gap[perm], log_hi[perm], log_lo[perm], log_cl[perm]
    no = np.empty(n); nc = np.empty(n); nh = np.empty(n); nl = np.empty(n)
    no[0], nc[0], nh[0], nl[0] = o[0], c[0], h[0], l[0]
    for i in range(1, n):
        no[i] = nc[i - 1] * np.exp(g[i - 1])
        nc[i] = no[i] * np.exp(cl[i - 1])
        nh[i] = no[i] * np.exp(hi[i - 1])
        nl[i] = no[i] * np.exp(lo[i - 1])
    out = df.copy()
    out["open"], out["close"], out["high"], out["low"] = no, nc, nh, nl
    return out


def permutation_pvalue(candidate, candles: dict, cfg: dict, n_perms: int = 100,
                       window: int = WINDOW, seed: int = 0) -> dict:
    """MCPT p-value for a candidate on `candles` (net P&L as the metric). Report-only.
    Returns {permutation_p, obs_net, n_perms, n_ge}. Reuses the event-driven backtester, so
    it scores exactly like the funnel does."""
    from src.backtester import Backtester
    from src.strategy import STRATEGY_REGISTRY
    from maker.grammar import compile as _compile
    fn = _compile(candidate)
    STRATEGY_REGISTRY[candidate.cid] = fn
    bcfg = _prepare_cfg(candidate, cfg)
    try:
        obs = _net(Backtester(bcfg, window=window).run(candles))
        rng = random.Random(seed)
        n_ge = 0
        for _ in range(n_perms):
            pc = {s: permute_ohlc(df, rng) for s, df in candles.items()}
            if _net(Backtester(bcfg, window=window).run(pc)) >= obs:
                n_ge += 1
    finally:
        STRATEGY_REGISTRY.pop(candidate.cid, None)
    return {"permutation_p": round((1 + n_ge) / (n_perms + 1), 4),
            "obs_net": round(obs, 2), "n_perms": n_perms, "n_ge": n_ge}
