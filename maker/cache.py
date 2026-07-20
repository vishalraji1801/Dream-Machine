"""maker/cache.py — indicator cache (Strategy Maker, spec section 16.1).

Candidates share blocks; blocks share indicators. Compute each indicator ONCE per
(symbol, tf, indicator, params, span_hash) and reuse across all trials. The span_hash
encodes the reserve/screen split, so a screen-stage lookup can NEVER collide with a
reserve-stage entry — the cache is structurally incapable of leaking reserve values
into a search run. Correctness-preserving: cached and uncached results are identical.
"""
import hashlib


def span_hash(symbol: str, tf: str, start, end, stage: str) -> str:
    """Cache-span key. `stage` ('screen'|'reserve') is part of the hash, so screen and
    reserve entries live in disjoint keyspaces."""
    raw = f"{symbol}|{tf}|{start}|{end}|{stage}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _pkey(params: dict):
    return tuple(sorted((k, str(v)) for k, v in params.items()))


class IndicatorCache:
    def __init__(self):
        self._store = {}
        self.computes = 0          # count of actual computations (cache misses)

    def get_or_compute(self, symbol, tf, indicator, params, span, compute_fn):
        key = (symbol, tf, indicator, _pkey(params), span)
        if key not in self._store:
            self.computes += 1
            self._store[key] = compute_fn()
        return self._store[key]

    def keys(self):
        return list(self._store)

    def spans_used(self):
        return {k[-1] for k in self._store}
