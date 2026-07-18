# Strategy Maker — Build Spec (for Claude Code)

Status: IN BUILD. Depends on (all existing in Dream Machine): backtester.py,
validation.py (walk-forward), costs.py (delivery/intraday/futures models),
backtest_store.py (full F&O daily history — Phase 0 item; DONE 2026-07-17, 214 names),
strategy.py framework (`fn(symbol, df, cfg) -> TradeSignal`), regime/market_state.

Instruction: implement following the commit sequence, one commit per step, tests
green after each.

---

## 0. Purpose & the three governing rules

Generate strategy candidates from a constrained grammar of building blocks, screen
them cheaply, run survivors through the existing gauntlet, and give finalists exactly
one shot at a locked reserve holdout. The machine's job is to make failed candidates
cost minutes and to make the rare survivor trustworthy.

RULE 1 — Every evaluation is a logged trial. The trial registry is append-only.
The acceptance bar rises with total trial count N. Deleting or not-recording a trial
is the one unforgivable bug in this system.

RULE 2 — The reserve holdout is locked and single-shot. The most recent
`reserve_months` (default 18) of every symbol's history is cut off before generation
begins. No generator, screener, tuner, or gauntlet run may read it. A candidate that
passes the gauntlet gets ONE reserve evaluation, ever. Fail -> status DEAD, permanent.
A modified candidate is a NEW candidate (new id, new trial).

RULE 3 — Parsimony budget. Max 3 condition blocks and max 4 tunable parameters
per candidate. Enforced at generation time; the generator cannot emit a candidate
over budget.

Everything inherits Dream Machine invariants: candidates compile to pure functions
(candles in -> TradeSignal out, no I/O, no now()), identical bytes in
backtest/paper/live, all results persisted with config_version.

---

## 1. Block library (maker/blocks.py)

Each block is a pure, parameterized predicate/action over a daily OHLCV frame (+
MarketState where noted). Blocks declare their param grid; the generator samples
from these grids only. Every block REQUIRES a non-empty rationale (economic story).

Slots: universe | regime | setup | trigger | exit | hold.

Initial library:
- universe: liquidity_floor {min_turnover_cr:[25,50]}, price_band {band:[[100,5000]]}
- regime: trend_side {ma:[100,200], side:[above,below]}, adx_band {min:[0,20,25],
  max:[20,25,100]}, bb_width_pctile {below:[15,25], above:[75,85]}
- setup: nday_extreme {lookback:[50,100,150,200], side:[high,low]}, pullback_depth
  {from_high_pct:[5,10,15], within_trend_ma:[200]}, compression {bbw_pctile_below:
  [10,15,25], min_bars:[5,10]}, flush {down_pct_in_bars:[[7,3],[10,5],[15,5]]}, gap
  {gap_pct_min:[2,3,5], direction:[up,down]}, band_touch {bollinger:[[20,2.0],[20,2.5]],
  side:[lower,upper]}
- trigger: breakout_close {of:[setup_level,prior_day_high,prior_day_low]}, limit_below
  {offset_pct:[0,2,3,5]}, confirm_candle {accept:[[hammer_white,doji]], above_vwap:[true]},
  resume_new_high {within_bars:[3,5]}
- exit: atr_trail {mult:[3,4,5,6], period:[14]}, r_multiple {r:[1.5,2,3]}, opposite_band
  {bollinger:[[20,2.0]]}, ma_cross_exit {ma:[20,50]}
- hold: time_stop {max_days:[10,20,40]}, min_expected_hold {min_days:[3,5]}

## 2. Candidate & grammar (maker/grammar.py)

Candidate(cid, direction[long|short|both], blocks{slot->BlockInstance}, n_conditions
(<=3), n_params (<=4), rationale, cost_check). compile(c) -> pure fn conforming to the
existing framework so the ENTIRE gauntlet/cost/paper engine works unchanged. Same cid
-> byte-identical behavior. Generation: exhaustive(sub-grammar) | neighborhood(seed) |
random(n, seed).

## 3. Generation-time rejects (maker/constraints.py) — free kills

Reject + log as GEN_REJECT: over parsimony budget; turnover budget fail (expected hold
< min OR gross edge/trade < cost_multiple_min (3x) * round-trip cost — delivery 0.24%
-> gross >= ~0.72%); direction=short with product=CNC; duplicate/param-twin cid.

## 4. Trial registry (maker/registry.py, SQLite `trials`) — RULE 1

Append-only (no UPDATE/DELETE path). family = hash(block structure + direction),
IGNORING timeframe and params. N_effective = distinct families at SCREEN+. Bar:
pf_required(N) = 1.2 + 0.15*log10(max(N,10)/10) -> N=10:1.20, N=100:1.35, N=1000:1.50.
Same bar at gauntlet AND reserve; stamped into each trial row.

## 5. Cheap screen (maker/screen.py)

One fast in-sample pass on SCREEN span (never reserve), full costs: kill if trades<30,
PF<1.1, net<=0; kill if >60% of net from top-3 trades. Survivors -> gauntlet, ranked
by PF*log(trades). ~90% kill; seconds/candidate.

## 6. Gauntlet integration (maker/run_gauntlet.py)

Existing gates per survivor: walk-forward OOS, stability, blue-chip (on broadened
universe incl losers/sideways), correct costs, plateau, slippage, multi-symbol.
Acceptance uses pf_required(N_effective). Hardening: purged walk-forward (embargo
max_hold bars, drop straddling trades); clustered trade counting (same-day same-dir
across correlated names = 1 cluster; >=30 OOS counts CLUSTERS); final pass under the
portfolio position cap (max 5 concurrent).

## 7. Reserve holdout (maker/reserve.py) — RULE 2

reserve_lock.json written ONCE {cutoff_date, symbols, hash}; store refuses reads past
cutoff unless caller==reserve.py. evaluate_once(family): ONE reserve shot per FAMILY.
When a family's best (TF,params) passes the gauntlet, THAT combo gets the family's
single reserve eval. FAIL -> family DEAD (all variants, permanent). PASS -> ALIVE at
that (TF,params). Reserve roll-forward every 6 months as a logged epoch.

## 8. Paper & portfolio admission

ALIVE -> paper under swing gate (>=8-12 weeks, >=30 round trips, per-strategy PF>=1.2,
paper-vs-backtest divergence<30%). Live-router admission also requires daily-return
correlation < 0.7 with each live strategy, else replaces its correlated sibling.

## 9. Tests (acceptance criteria)

1 grammar->pure fn (no I/O/kite/now); 2 parsimony impossible >3cond/>4param; 3 turnover
reject with cost math; 4 registry immutable + N_effective counts families; 5 bar exact
at N=10/100/1000; 6 screen kills (<30 trades, outlier-carried); 7 reserve lock (non-
reserve read past cutoff raises); 8 single-shot (2nd evaluate raises; modified->new
cid); 9 determinism (same cid+span -> identical metrics hash); 10 end-to-end 50-cand
seeded run (counts consistent).

## 10. Commit sequence

1 blocks.py + rationale + tests 1-2. 2 grammar.py compile() + det test 9. 3
constraints.py rejects + test 3. 4 registry.py + bar.py + tests 4-5. 5 screen.py + test
6. 6 reserve.py lock + single-shot + tests 7-8 (BEFORE gauntlet wiring). 7
run_gauntlet.py + trial-adjusted bar. 8 paper admission + correlation. 9 end-to-end +
test 10. CLI: bot.py make generate|screen|gauntlet|reserve|status.

## 11. Dual-sleeve extension — intraday + swing

Candidate gains sleeve[swing|intraday], timeframe, product(swing->CNC, intraday->MIS).
Cost dispatch per sleeve. Intraday MUST include square_off hold block. Shorts allowed
intraday, rejected CNC. Intraday block jars: session_windows(time_window,
skip_open_minutes), setups_intraday(opening_range, vwap_relation, intraday_flush,
prior_day_level), triggers_intraday(candle_confirm_1m, new_extreme_after_pullback),
filters_intraday(rvol_gate, scanner_rank), hold_intraday(square_off MANDATORY,
max_hold_min). Intraday turnover budget: gross >= 3x*(0.08%+0.10% slip) ~ 0.54%.
Slippage in SCREEN (intraday). Session-robustness gate. N_effective per sleeve; seed
swing with prior 19-strategy campaign, intraday with 56 trials (14x4TF, FAIL) -> bar
starts ~1.31. prior_falsified_region guard (fixed-list/all-day/large-cap intraday
GEN_REJECT without override). Intraday inert while intraday.enabled=false. Additional
tests 11-16. Commit additions 10-15.

## 12. Data layer — Nifty 50, all timeframes

Native storage: 1-min + daily only; all other TFs resampled from 1-min (origin 09:15,
closed bars). Universe: Nifty 50 + recent ex-constituents. Corporate-action adjustment
(CRITICAL): intraday candles NOT split-adjusted — maintain adjustment-factor table,
apply on load, reconciliation test (adjusted-1min-derived daily == native daily),
data_version epoch on new CA. Every (candidate x TF) = separate trial. TF->sleeve
auto-map. tf_spike coherence gate. Tests 17-22. Commit additions 16-20.

## 13. Indicator module (indicators.py — pinned, in-house)

No TA-Lib/pandas-ta. Wilder smoothing for RSI/ATR/ADX. Pinned set (trend/strength/
volatility/volume/structure/regime). Golden-fixture test per indicator (exact to 6dp).
Params only from block grids. TF-agnostic.

## 14. Fibonacci & swing detection (indicators/swings.py, indicators/fib.py)

N-bar pivot: extreme of N bars each side. Confirmation lag: pivot exists only N bars
after it forms (no look-ahead, enforced + tested). Fib blocks: pullback_to_fib
(382/500/618, tolerance_atr, swing_n), fib_extension_target (1272/1618/2000).

## 15. Support & Resistance (indicators/levels.py)

Four tiers preferred in order: 1 objective (prior H/L/C, OR, round, 52w, gaps — zero
params); 2 volume profile (POC/HVN/LVN/VA); 3 pivot clusters (>=touch_min, strength =
touches*recency); 4 fib. Blocks: bounce_at_level, break_of_level, reject_at_level.
Levels are ZONES (width 0.25*ATR), not lines. Detection params count against the 4-
param budget (tier-1 exempt). Tests 17-22. Commit additions 16-20.

## 16. Compute plan — making 2,100 trials cheap

Correctness-preserving only. Indicator cache keyed by (symbol,tf,indicator,params,
data_span_hash) — span_hash encodes reserve/screen split (cache cannot leak reserve).
Materialized resample cache. Staged screen: GEN_REJECT (free) -> trade-count pre-check
(~10 symbols) -> Stage A (subset, 3yr) -> Stage B (full). Vectorized screen must be
CONSERVATIVE vs replay (test 24). Multiprocessing pool; single-writer registry (WAL).
Budget guard. Tests 23-27. Commit additions 21-26.

## 17. Definition of done

All tests pass; reserve-isolation test in default suite forever. Seeded 200-candidate
campaign runs end-to-end; `bot.py make status` prints N_effective, pf_required, stage
counts. Zero candidates evaluated before reserve_lock.json existed. Expectation in
writing: 2-3 ALIVE out of ~300 is a successful year; zero is a possible honest outcome.
Intraday: zero survivors is the LIKELY outcome given 56 prior failures. Statistical
unit is the FAMILY (block structure + direction, ignoring TF and params).
