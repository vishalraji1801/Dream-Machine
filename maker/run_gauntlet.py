"""maker/run_gauntlet.py — gauntlet wiring (Strategy Maker, spec section 6).

Screen survivors run through the existing rigor: sweep the family's tunable params
(the plateau — neighbours in each block's own grid), pick the best set IN-SAMPLE, test
it OUT-OF-SAMPLE, and accept only if the OOS PF clears pf_required(N_effective) — not
a static 1.2. Records a GAUNTLET trial either way (RULE 1).

Hardening still to land (spec section 6, later commits): purged walk-forward embargo,
clustered trade counting across correlated names, and a max-5 portfolio-cap final
pass. This commit wires the core in-sample-select / OOS-test / plateau / rising-bar
loop; those three additions tighten it without changing its shape.
"""
import itertools

from maker.bar import pf_required
from maker.blocks import BLOCKS
from maker.grammar import make_candidate
from maker.screen import WINDOW, screen_candidate

MIN_TRADES = 20
PLATEAU_MIN_PF = 1.2


def tunable_axes(candidate) -> list:
    """(slot, block_name, param, [grid values]) for each genuinely tunable param."""
    axes = []
    for slot, bi in candidate.blocks.items():
        grid = BLOCKS[bi.name].params
        for p in bi.params:
            if len(grid[p]) > 1:
                axes.append((slot, bi.name, p, list(grid[p])))
    return axes


def variants(candidate, cap: int = 24) -> list:
    """Candidate variants over the tunable axes (the plateau neighbourhood)."""
    axes = tunable_axes(candidate)
    combos = list(itertools.product(*[a[3] for a in axes])) or [()]
    if len(combos) > cap:                         # even subsample to bound compute
        combos = combos[:: max(1, len(combos) // cap)][:cap]
    out = []
    for combo in combos:
        blocks = {slot: (bi.name, dict(bi.params)) for slot, bi in candidate.blocks.items()}
        for (slot, _n, p, _v), val in zip(axes, combo):
            blocks[slot][1][p] = val
        out.append(make_candidate(candidate.direction, blocks))
    return out


def _time_split(candles: dict, frac: float = 0.7):
    ins, oos = {}, {}
    for s, df in candles.items():
        cut = int(len(df) * frac)
        ins[s] = df.iloc[:cut].reset_index(drop=True)
        oos[s] = df.iloc[cut:].reset_index(drop=True)
    return ins, oos


def run_gauntlet(candidate, candles: dict, cfg: dict, registry, family: str,
                 n_effective: int, window: int = WINDOW) -> tuple[bool, object, dict]:
    bar = pf_required(n_effective)
    ins, oos = _time_split(candles)
    vs = variants(candidate)

    scored = []                                   # in-sample PF per variant (plateau)
    for v in vs:
        _, _, m = screen_candidate(v, ins, cfg, window=window)
        scored.append((v, m))
    plateau_pass = sum(1 for _, m in scored
                       if m["pf"] >= PLATEAU_MIN_PF and m["trades"] >= MIN_TRADES)
    best_v, _best_m = max(scored,
                          key=lambda t: t[1]["pf"] if t[1]["trades"] >= MIN_TRADES else 0)

    _, _, oos_m = screen_candidate(best_v, oos, cfg, window=window)   # OOS test of the winner
    passed = (oos_m["pf"] >= bar and oos_m["trades"] >= MIN_TRADES and oos_m["net"] > 0
              and plateau_pass >= max(1, len(vs) // 2))
    metrics = {"oos_pf": oos_m["pf"], "oos_trades": oos_m["trades"], "oos_net": oos_m["net"],
               "plateau": f"{plateau_pass}/{len(vs)}",
               "best_params": {slot: dict(bi.params) for slot, bi in best_v.blocks.items()}}
    registry.record(best_v.cid, family, "GAUNTLET", "PASS" if passed else "FAIL",
                    pf_required=bar, metrics=metrics)
    return passed, best_v, metrics
