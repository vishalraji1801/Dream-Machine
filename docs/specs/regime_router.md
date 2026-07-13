# Regime Router & Parameter Adaptation — Build Spec

Status: IN BUILD. Depends on: MarketState layer, strategy registry, SQLite ledger
(mode/run_id/config_version tagging), fixed-fractional sizer, overlay validation,
walk-forward harness.

## 0. Purpose & the one rule that governs everything

Two capabilities:
1. **Strategy adaptation** — enable/weight strategies by current market regime.
2. **Parameter adaptation** — let each strategy use regime-appropriate parameters.

**THE GOVERNING RULE:** adaptation may only ever *select from pre-validated options*
or *scale by a fixed formula*. It may **never** invent, fit, or deploy a parameter
that has not passed walk-forward out-of-sample validation.

Three levels, ascending danger. Build 1 and 2. Treat 3 as paper-only research.

## 1. Design invariants
- **Pure & mode-blind:** classifier, router, and parameter selection are pure
  (state in → decision out). No `datetime.now()` (pass `now`), no Kite imports, no I/O.
- **No look-ahead:** regime computed only from **closed** bars as of `now`.
- **Everything persisted:** regime label, chosen param set, strategy weights written
  to `trades.db` per cycle with `mode`, `run_id`, `config_version`.
- **Hard bounds enforced:** every adaptive value passes overlay validation or the bot
  falls back to defaults and alerts.
- **Fail-safe direction:** adaptation may *downsize or disable*; premarket sets the
  ceiling, intraday can only lower it.

## 2. Regime classifier (`regime.py`, pure)
`Regime`: STRONG_TREND_UP, STRONG_TREND_DOWN, RANGE, HIGH_VOL_CHOP, QUIET, UNKNOWN.
`RegimeState`: regime, confidence(0..1), since_bars, inputs, config_version.
`classify(state: MarketState, prev, cfg, now) -> RegimeState`.
- Inputs: trend (EMA slope/side), ADX, ATR%, BB-width percentile, breadth.
- Hysteresis/dwell: a new regime commits only after `min_dwell_bars` (anti-whipsaw).
- confidence scales with how far inputs clear thresholds.
- Only closed bars; `now` is a parameter.

## 3. Strategy metadata — regime validity + parameter sets
Each strategy declares (config) which regimes it may run in + a menu of pre-validated
param sets keyed by regime (`regime_param_sets`), plus measured `regime_fit` (PF/trades).
- A set with `validated: false` is NEVER selected in live/paper (research mode only).
- `oos_ref` points to the walk-forward run that proved the set.
- Level 1: the system *selects* a proven set for the regime.

## 4. Level 2 — formula-scaled parameters (no fitting)
ATR-unit stops/targets, 1/ATR position size, RVOL relative to time-of-day baseline.
Pure functions of MarketState. Move adaptivity here wherever possible.

## 5. Router (`router.py`, pure)
`route(regime, strategies, premarket, cfg) -> list[ActiveStrategy]`.
- Look up each strategy's set for the regime; skip if disabled/unvalidated.
- **Weight, don't hard-switch:** weight ∝ regime_fit.pf × confidence, normalized.
- Hysteresis on weights (cap per-cycle change).
- Fail-safe: clamp total to premarket ceiling; may lower to 0, never exceed.
- "Trade nothing" is valid (all fits < 1 → empty).
- Persist all routing decisions.

## 6. The learned map — regime→fit from the ledger (analyst, offline)
Scheduled job computes per (strategy × regime): PF, expectancy, trades, net of costs,
writes into `regime_fit`. Only buckets with ≥ min_trades (e.g. 30); below → neutral,
not a guess. Walk-forward confirmation required before a fit is trusted live.

## 7. Level 3 — continuous re-optimization (PAPER-ONLY, guardrailed)
propose → validate → maybe deploy, never auto-deploy. Immutable min/max per param;
risk caps not tunable. ≤10% move per approved update. Mandatory drift audit vs fixed
baseline; auto-revert if not beating baseline.

## 8. Tests (acceptance)
1. Classifier determinism. 2. Hysteresis. 3. No look-ahead. 4. Unvalidated set blocked.
5. Weighting ratio. 6. Fail-safe ceiling. 7. Trade-nothing. 8. Small sample neutral.
9. Bounds rejection + fallback. 10. Drift audit flags underperformance.

## 9. Commit sequence (one per commit, tests green after each)
1. `regime.py` classifier + hysteresis + tests 1–3 (pure).
2. Strategy metadata schema (regime_param_sets, regime_fit) + loader + validated-flag + test 4.
3. Level 2 formula-scaled parameter functions + tests.
4. `router.py` weighting + fail-safe + trade-nothing + tests 5–7.
5. Ledger persistence of regime/param-set/weights per cycle.
6. Analyst map job: ledger → regime_fit + small-sample guard + test 8.
7. Overlay-bound enforcement for adaptive params + fallback/alert + test 9.
8. (Optional) Level 3 propose→validate scaffolding + drift audit + test 10 — paper-only.
9. Backtest the whole router through walk-forward; report vs baselines.

## 10. Definition of done
All 10 tests pass; classifier + router pure; walk-forward shows routed vs baselines OOS;
no unvalidated param reaches live; no param exceeds hard bounds; drift audit auto-reverts.

---
Adaptation *feels* like sophistication but usually subtracts performance. Build Levels
1–2 with confidence; make Level 3 prove itself in paper for a long time.
