"""maker/parallel_campaign.py — process-parallel campaign (Strategy Maker, spec section 16.5).

Same funnel as maker.campaign.run_campaign, run across a process pool. The screen+gauntlet
of each candidate is CPU-bound pure-Python (GIL-bound bar replay), so real speedup needs
processes, not threads — ~linear in cores on one box (no Spark/Ray: the data is sub-GB and
the parallelism is task-parallel, not data-parallel).

Determinism and the three RULES are preserved by a strict parent/worker split:

  PARENT (this process) owns the registry, the RNG, and the reserve lock:
    1. pre-generates all candidates from Random(seed)         -> reproducible, worker-count independent
    2. runs constraints.check in order, building `seen`        -> identical GEN_REJECTs to serial
    3. precomputes each survivor's gauntlet bar (N_effective)  -> a pure function of candidate ORDER,
                                                                  not wall-clock finish order
    4. records EVERY trial itself, in original order           -> RULE 1: one writer, serial insertion
    5. runs the reserve step serially                          -> RULE 2: one single-shot per family

  WORKERS are strictly READ-ONLY: they screen+gauntlet a candidate against a fixed bar and
  return metrics. They never touch the DB, the RNG, or the reserve data.

The result is byte-identical to serial run_campaign for the same seed (asserted by test).
"""
import os
import random
from concurrent.futures import ProcessPoolExecutor

from maker import constraints
from maker.bar import pf_required
from maker.generate import random_candidate
from maker.registry import EVALUATED_STAGES, family_id
from maker.run_gauntlet import run_gauntlet
from maker.screen import WINDOW, fast_screen_candidate


# ── worker side (module-level so Windows 'spawn' can pickle them by reference) ──
_G = {}


def _init_worker(cfg, candles, window):
    _G["cfg"], _G["candles"], _G["window"] = cfg, candles, window


class _NullRegistry:
    """A registry the gauntlet can 'record' into without writing — the parent does the
    real, ordered write. n_effective is never read (the bar is passed in precomputed)."""
    def record(self, *a, **k):
        return 0


def _eval_worker(task):
    """Screen + (if it survives) gauntlet ONE candidate against a fixed bar. Pure read."""
    index, cand, bar = task
    cfg, candles, window = _G["cfg"], _G["candles"], _G["window"]
    fam = family_id(cand)
    passed, sreason, m = fast_screen_candidate(cand, candles, cfg, window=window)
    out = {"index": index, "family": fam, "screen": (passed, sreason, m), "bar": bar}
    if passed:
        gpassed, best, gm = run_gauntlet(cand, candles, cfg, _NullRegistry(), fam, bar,
                                         window=window)
        out["gauntlet"] = (gpassed, best, gm)
    return out


# ── parent side ────────────────────────────────────────────────────────────────

def run_campaign_parallel(n: int, seed: int, candles: dict, cfg: dict, registry,
                          lock: dict = None, product: str = "delivery", window: int = None,
                          workers: int = None, time_budget_s: float = None) -> dict:
    import time
    started = time.time()
    window = WINDOW if window is None else window
    workers = workers or max(1, min(8, (os.cpu_count() or 2) - 2))
    counts = {"generated": 0, "gen_reject": 0, "screened": 0, "screen_fail": 0,
              "gauntlet_run": 0, "gauntlet_fail": 0, "reserve_run": 0, "alive": 0,
              "workers": workers}

    screen_cs = candles
    if lock is not None:
        from maker.reserve import screen_candles
        screen_cs = {s: screen_candles(df, lock) for s, df in candles.items()}

    long_only = product.lower() in ("delivery", "cnc")
    rng = random.Random(seed)

    # 1-3: generate, constraint-check, and precompute the gauntlet bar — all in the
    # parent, all a pure function of candidate ORDER (matches serial exactly).
    seen = set()
    fams_evaluated = {r["family"] for r in registry.rows()
                      if r["stage"] in EVALUATED_STAGES}          # seed bar from prior search
    plan = []                    # ordered: (index, cand, fam, gen_reject|None, bar|None)
    for k in range(n):
        cand = random_candidate(rng, direction="long" if long_only
                                else rng.choice(["long", "short"]))
        counts["generated"] += 1
        fam = family_id(cand)
        ok, reason, detail = constraints.check(cand, product=product, seen_cids=seen)
        seen.add(cand.cid)
        if not ok:
            plan.append((k, cand, fam, (reason, detail), None))
            continue
        fams_evaluated.add(fam)                                   # this candidate reaches SCREEN
        plan.append((k, cand, fam, None, len(fams_evaluated)))    # bar = live N_effective

    # how many screen-bound candidates to actually run (budget truncates the tail; a
    # prefix, so recording order and determinism are preserved). Budget is best-effort:
    # once already over budget at fan-out time, submit nothing further.
    import time
    n_screen_bound = sum(1 for (_, _, _, rej, _) in plan if rej is None)
    to_run = n_screen_bound
    if time_budget_s is not None and (time.time() - started) > time_budget_s:
        to_run = 0

    # 4: farm the expensive screen+gauntlet across the pool, but RECORD INCREMENTALLY as
    # ordered results stream back — so a killed 14-hour run keeps every finished trial
    # (RULE 1: one writer, insertion order). ex.map yields in submission order == plan
    # order of screen-bound candidates, so we consume it in lockstep with the plan walk.
    from maker.reserve import evaluate_once

    def _record_all(result_iter):
        seen_run = 0
        for (k, cand, fam, rej, bar) in plan:
            if rej is not None:
                reason, detail = rej
                registry.record(cand.cid, fam, "GEN_REJECT", "FAIL", metrics=detail,
                                notes=reason)
                counts["gen_reject"] += 1
                continue
            if seen_run >= to_run:                               # dropped by budget
                counts["stopped_on_budget"] = True
                continue
            r = next(result_iter)
            seen_run += 1
            passed, sreason, m = r["screen"]
            registry.record(cand.cid, fam, "SCREEN", "PASS" if passed else "FAIL",
                            metrics=m, notes=sreason)
            counts["screened"] += 1
            if not passed:
                counts["screen_fail"] += 1
                continue
            gpassed, best, gm = r["gauntlet"]
            # mirror run_gauntlet's own record: pf_required stores the PF THRESHOLD
            # pf_required(N), not the integer N_effective (`bar`) the worker was gated on.
            registry.record(best.cid, fam, "GAUNTLET", "PASS" if gpassed else "FAIL",
                            pf_required=pf_required(bar), metrics=gm)
            counts["gauntlet_run"] += 1
            if not gpassed:
                counts["gauntlet_fail"] += 1
                continue
            if lock is not None:                                 # RULE 2: serial, in-parent
                status, _ = evaluate_once(best, fam, candles, lock, registry,
                                          registry.n_effective(), cfg)
                counts["reserve_run"] += 1
                if status == "ALIVE":
                    counts["alive"] += 1

    tasks = [(k, cand, bar) for (k, cand, fam, rej, bar) in plan if rej is None][:to_run]
    if tasks:
        with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker,
                                 initargs=(cfg, screen_cs, window)) as ex:
            _record_all(iter(ex.map(_eval_worker, tasks)))
    else:
        _record_all(iter(()))
    return counts
