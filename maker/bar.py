"""maker/bar.py — trial-adjusted acceptance bar (Strategy Maker, spec section 4).

The bar rises with the number of independent ideas tried (N_effective = distinct
FAMILIES evaluated at screen or beyond). More search -> a higher hurdle, so the rare
survivor is trustworthy rather than the max of a large lottery.

    pf_required(N) = base_pf + k * log10(max(N, 10) / 10)

    N=10   -> 1.20     N=100  -> 1.35     N=1000 -> 1.50

Simple, monotone, auditable. The value used is stamped into each trial row. The SAME
bar applies at the gauntlet AND the reserve stage.
"""
import math

BASE_PF = 1.2
K = 0.15


def pf_required(n_effective: int, base_pf: float = BASE_PF, k: float = K) -> float:
    return round(base_pf + k * math.log10(max(n_effective, 10) / 10.0), 4)
