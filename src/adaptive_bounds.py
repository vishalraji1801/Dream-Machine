"""
Hard-bounds enforcement for adaptive parameters (regime router, commit 7).

Every value the router is about to use must survive the same immutable bounds the
AI overlay is held to. A regime param set that proposes an out-of-bounds value is
rejected; the strategy falls back to its `default` set (if that is in bounds) or is
disabled — always with an alert. Risk caps and capital are never adjustable and are
not in this surface at all.
"""
from typing import Optional

from src.overlay import _STRATEGY_BOUNDS

# The adaptive-parameter bounds default to the overlay's strategy bounds; callers
# may pass an extended dict as real strategies add their own tunables.
DEFAULT_BOUNDS: dict = dict(_STRATEGY_BOUNDS)


def validate_params(params: dict, bounds: Optional[dict] = None) -> Optional[str]:
    """Return an error string for the first out-of-bounds numeric param, else None.
    Params without a declared bound are not adaptive-tunable here and pass through
    (they must be validated elsewhere, e.g. select-from-menu / formula-scaled)."""
    b = DEFAULT_BOUNDS if bounds is None else bounds
    for key, val in (params or {}).items():
        if key in b and isinstance(val, (int, float)) and not isinstance(val, bool):
            lo, hi = b[key]
            if not (lo <= val <= hi):
                return f"{key}={val} outside [{lo}, {hi}]"
    return None
