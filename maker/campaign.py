"""maker/campaign.py — end-to-end funnel (Strategy Maker, spec section 9).

Runs generated candidates through constraints -> screen -> gauntlet -> (reserve),
recording a trial at every stage (RULE 1). Counts are internally consistent:
    generated = gen_reject + screened
    screened  = screen_fail + gauntlet_run
    gauntlet_run = gauntlet_fail + reserve_run   (when a reserve lock is supplied)
"""
import random

from maker import constraints
from maker.generate import random_candidate
from maker.registry import family_id
from maker.run_gauntlet import run_gauntlet
from maker.screen import screen_candidate


def run_campaign(n: int, seed: int, candles: dict, cfg: dict, registry,
                 lock: dict = None, product: str = "delivery", window: int = 160) -> dict:
    rng = random.Random(seed)
    counts = {"generated": 0, "gen_reject": 0, "screened": 0, "screen_fail": 0,
              "gauntlet_run": 0, "gauntlet_fail": 0, "reserve_run": 0, "alive": 0}
    seen = set()

    if lock is not None:
        from maker.reserve import screen_candles
        screen_cs = {s: screen_candles(df, lock) for s, df in candles.items()}
    else:
        screen_cs = candles

    long_only = product.lower() in ("delivery", "cnc")
    for _ in range(n):
        cand = random_candidate(rng, direction="long" if long_only else rng.choice(["long", "short"]))
        counts["generated"] += 1
        fam = family_id(cand)

        ok, reason, detail = constraints.check(cand, product=product, seen_cids=seen)
        seen.add(cand.cid)
        if not ok:
            registry.record(cand.cid, fam, "GEN_REJECT", "FAIL", metrics=detail, notes=reason)
            counts["gen_reject"] += 1
            continue

        passed, sreason, m = screen_candidate(cand, screen_cs, cfg, window=window)
        registry.record(cand.cid, fam, "SCREEN", "PASS" if passed else "FAIL",
                        metrics=m, notes=sreason)
        counts["screened"] += 1
        if not passed:
            counts["screen_fail"] += 1
            continue

        gpassed, best, _gm = run_gauntlet(cand, screen_cs, cfg, registry, fam,
                                          registry.n_effective(), window=window)
        counts["gauntlet_run"] += 1
        if not gpassed:
            counts["gauntlet_fail"] += 1
            continue

        if lock is not None:
            from maker.reserve import evaluate_once
            status, _rm = evaluate_once(best, fam, candles, lock, registry,
                                        registry.n_effective(), cfg)
            counts["reserve_run"] += 1
            if status == "ALIVE":
                counts["alive"] += 1

    return counts
