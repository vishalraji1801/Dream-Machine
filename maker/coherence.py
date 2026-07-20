"""maker/coherence.py — timeframe-coherence gate (Strategy Maker, spec section 12.3).

A candidate that passes on exactly one timeframe while failing BOTH adjacent timeframes
is a tf_spike — a one-fold spike, not a robust edge. It is flagged and not accepted
without an explicit hypothesis for why that timeframe is special (logged on the trial).

Adjacency (section 16.6): 1m - 3m - 5m - 15m - 30m - 60m - 1d - 1w.
"""
TF_ORDER = ["1m", "3m", "5m", "15m", "30m", "60m", "1d", "1w"]


def adjacent(tf: str) -> list:
    if tf not in TF_ORDER:
        return []
    i = TF_ORDER.index(tf)
    neigh = []
    if i > 0:
        neigh.append(TF_ORDER[i - 1])
    if i < len(TF_ORDER) - 1:
        neigh.append(TF_ORDER[i + 1])
    return neigh


def is_tf_spike(tf: str, passed_by_tf: dict, has_hypothesis: bool = False) -> bool:
    """passed_by_tf: {timeframe: passed?}. A spike = passes on `tf` but BOTH evaluated
    adjacent timeframes fail. An explicit hypothesis exempts it."""
    if has_hypothesis:
        return False
    if not passed_by_tf.get(tf):
        return False
    evaluated_neighbours = [t for t in adjacent(tf) if t in passed_by_tf]
    if len(evaluated_neighbours) < 2:            # need both adjacent TFs evaluated
        return False
    return all(not passed_by_tf[t] for t in evaluated_neighbours)


def coherence_verdict(passed_by_tf: dict, has_hypothesis: bool = False) -> dict:
    """Per-TF acceptance after the coherence gate. A tf_spike is downgraded to not
    accepted (flagged) unless a hypothesis is declared."""
    out = {}
    for tf, passed in passed_by_tf.items():
        spike = is_tf_spike(tf, passed_by_tf, has_hypothesis)
        out[tf] = {"passed": passed, "tf_spike": spike, "accepted": passed and not spike}
    return out
