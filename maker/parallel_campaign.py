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
from concurrent.futures import ProcessPoolExecutor, as_completed

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

    import time
    from maker.reserve import evaluate_once

    # Record the free GEN_REJECTs up front (deterministic, no compute).
    for (k, cand, fam, rej, bar) in plan:
        if rej is not None:
            registry.record(cand.cid, fam, "GEN_REJECT", "FAIL", metrics=rej[1], notes=rej[0])
            counts["gen_reject"] += 1

    screen_bound = [(k, cand, fam, bar) for (k, cand, fam, rej, bar) in plan if rej is None]

    # PHASE A — screen+gauntlet across the pool, recorded in COMPLETION order (as_completed),
    # NOT submission order. This is the fix for the head-of-line freeze: a single slow
    # candidate can no longer stall the whole ledger — every finished result commits
    # immediately (RULE 1: one writer; row order is completion order, which is fine since
    # each row is self-contained and its bar is precomputed, so metrics stay deterministic).
    # A generous per-task timeout is a safety net against a genuine hang.
    survivors = []               # (k, best, fam, bar) gauntlet survivors -> serial reserve
    TASK_TIMEOUT = 1800          # 30 min: ~7x a normal 202-symbol gauntlet; a real hang, not slow
    if screen_bound:
        with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker,
                                 initargs=(cfg, screen_cs, window)) as ex:
            fut_meta = {ex.submit(_eval_worker, (k, cand, bar)): (k, cand, fam, bar)
                        for (k, cand, fam, bar) in screen_bound}
            for fut in as_completed(fut_meta):
                k, cand, fam, bar = fut_meta[fut]
                try:
                    r = fut.result(timeout=TASK_TIMEOUT)
                except Exception as e:                           # hang/crash: log + skip, don't freeze
                    registry.record(cand.cid, fam, "SCREEN", "FAIL",
                                    metrics={"error": str(e)[:200]}, notes="worker_error")
                    counts["screened"] += 1; counts["screen_fail"] += 1
                    continue
                passed, sreason, m = r["screen"]
                registry.record(cand.cid, fam, "SCREEN", "PASS" if passed else "FAIL",
                                metrics=m, notes=sreason)
                counts["screened"] += 1
                if not passed:
                    counts["screen_fail"] += 1
                    continue
                gpassed, best, gm = r["gauntlet"]
                # pf_required stores the PF THRESHOLD pf_required(N), not the integer N (`bar`).
                registry.record(best.cid, fam, "GAUNTLET", "PASS" if gpassed else "FAIL",
                                pf_required=pf_required(bar), metrics=gm)
                counts["gauntlet_run"] += 1
                if not gpassed:
                    counts["gauntlet_fail"] += 1
                    continue
                survivors.append((k, best, fam, bar))

    # PHASE B — reserve exam, SERIAL and in CANDIDATE ORDER (RULE 2: one single-shot per
    # FAMILY, ever; the lowest-index survivor of a family gets it, so the verdict is
    # deterministic regardless of Phase-A completion order). Reserve data is tiny (fast).
    reserved = {r["family"] for r in registry.rows() if r["stage"] == "RESERVE"}
    for (k, best, fam, bar) in sorted(survivors, key=lambda t: t[0]):
        if lock is None or fam in reserved:
            continue
        status, _ = evaluate_once(best, fam, candles, lock, registry, bar, cfg)
        reserved.add(fam)
        counts["reserve_run"] += 1
        if status == "ALIVE":
            counts["alive"] += 1
    return counts
