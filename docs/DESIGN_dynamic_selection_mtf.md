# Design — Condition-Based Stock Selection & Multi-Timeframe Confirmation

Status: **REVISED DRAFT v2** · 2026-07-08 · builds on V2 P3 (dormant scanner) and the
strategy registry.

**Design invariant:** one implementation of each idea, reused identically in
**backtest, paper, and live**. The only mode differences remain where they are
today: order execution + margin source (+ candle *source*, behind the existing
provider seam). Every new decision point (scanner score, MTF veto) is persisted
to `trades.db` with `mode`, `run_id`, and `config_version`, so conditional
analytics and live-vs-backtest divergence checks come free.

---

## Part A — Condition-based stock selection

### A.0 Problem (unchanged)
Fixed 50-name watchlist trades whatever those stocks do, not where the day's
movement is. 1-yr backtest confirmed: breakout/momentum edge on quiet
large-caps < transaction costs.

### A.1 What exists (built, opt-in, unvalidated)
`universe_builder.py` (daily filter) · `scanner.py` (per-cycle ranking) ·
`tick_candle_builder.py` · `stock_selector.py` (turnover + ATR% filters) ·
wiring behind `universe.enabled: false`.

### A.2 The work — with one data-plan correction

**A.2.1 RVOL — corrected data dependency.**
Time-of-day-adjusted RVOL needs a **per-symbol intraday cumulative-volume
profile** (average cumulative volume at each 15-min bucket over the last 20
sessions). The draft assumed this falls out of `stock_selector`'s 30-day
*daily* candles — it does not; daily bars carry no time-of-day shape.

Data plan — **bootstrap via REST once, then self-sufficient from ticks**:
- **Day 1 bootstrap (REST):** one historical call per pool symbol fetches weeks
  of 15-min candles in a single request; ~200 symbols at 2–3 req/s ≈ **90
  seconds**, run nightly-slot once (not pre-market — the 08:30–09:15 window is
  too tight). Seeds the 20-session bucket profiles.
- **Ongoing maintenance (WebSocket-derived, zero REST):** the full universe is
  already streamed all day and every tick carries `volume_traded` (day
  cumulative). The EOD job rolls each profile forward from the **tick-built
  candle archive** — same source as the live RVOL numerator, so profile and
  numerator can never disagree on data provenance. After 20 sessions the
  bootstrap data has fully aged out.
- **REST becomes gap-repair only:** if the bot was down for a session or a
  symbol is new to the pool, backfill just the missing sessions. Keep the code
  path; stop scheduling it.
- Live: RVOL(t) = cumvol_today(t) / profile(t), interpolated between bucket
  boundaries. Staleness guard: profile older than 3 sessions → symbol excluded
  from RVOL ranking rather than ranked on bad data. Tick-vs-official volume
  may differ ±1% (same tolerance as the candle consistency test) — acceptable
  for a ranking signal.

**A.2.2 Candle seeding for mid-day shortlist entrants.**
As drafted (tick_candle_builder first, REST fallback), plus one rule: a symbol
becomes **signal-eligible only after ≥ WARMUP_CANDLES closed bars** are
available, same constant as everywhere else. A seeded-but-short history must
not silently produce indicators computed on 7 bars.

**A.2.3 Point-in-time backtesting.**
As drafted, with two additions:
- Persist **full rankings for every universe symbol each cycle**, not only the
  top-30 — replays and threshold re-tuning need the losers too. Also log
  filtered-out candidates with rejection reason (turnover / ATR / circuit /
  churn), so filter thresholds are measurable later.
- Once tick-built candles are being archived daily, **prefer them over Kite
  historical candles** as backtest input for those dates (removes the
  self-built vs native candle parity gap from the loop).

**A.2.4 Safety rails for live — expanded.**
- **Churn with hysteresis:** enter shortlist after holding rank ≤ N for 2
  consecutive cycles; exit only after falling below rank N+k. Cap new
  additions per cycle (e.g., 3) so a market-wide spike doesn't rotate the
  whole book.
- **Sector cap:** scanner picks cluster (sector news moves 5 names at once);
  max 1–2 open positions per sector. This rail matters *more* under dynamic
  selection than it did with the fixed list.
- **Event exclusion:** symbols with earnings/corporate actions today are
  excluded at the universe stage (calendar file, maintained by the weekly
  Claude agent).
- Circuit-band exclusion and top-N-only REST spread check: as drafted
  (30 ≪ 500-symbol quote limit).

### A.3 Mode-by-mode (unchanged behavior, quantified gate)
| Mode | Behavior |
|---|---|
| Backtest | `backtest_run.py --universe`: per-bar scanner simulation over the stored pool; per-day universe files once they exist |
| Paper | `universe.enabled: true`; full universe streamed (≤3,000 ok); top-30 traded; weekly scanner audit by Claude agent |
| Live | identical code path; gate below |

**Go/no-go gate (replaces "≥ watchlist baseline"):** over ≥ 2 paper weeks and
≥ 60 scanner-picked trades, scanner cohort must show **expectancy ≥ 2× its avg
per-trade cost and PF ≥ 1.3, net of costs**, and beat the fixed-watchlist
cohort run in parallel over the *same sessions*. Note the comparison must be
net of *per-symbol* spread/slippage — movers carry wider spreads than sleepy
large-caps, and a gross comparison flatters the scanner.

### A.4 Phases
- **A0 (this week, before anything else):** start persisting daily universe
  files + full scanner rankings + rejected candidates. History accrues while
  B ships.
- A1: volume profiles — REST bootstrap (once) + EOD roll-forward from the tick
  archive + REST gap-repair path + RVOL scoring (+ offline scanner simulation
  for backtests). See `docs/specs/A1_volume_profiles.md` for the build spec.
- A2: candle seeding + signal-eligibility warm-up rule
- A3: backtester `universe_by_day` + `--universe` mode
- A4: paper enablement + rails (churn hysteresis, sector cap, events, circuit, spread)
- A5: paired cohort comparison report → go/no-go per A.3 gate

---

## Part B — Multi-timeframe (MTF) confirmation

### B.1 Design (unchanged)
Composition wrapper in front of any registered strategy; higher-TF trend gate;
disagreement → HOLD with reason `mtf_veto`, logged. Config schema as drafted.
**Phase-2 lower-TF timing gate stays deferred** — it multiplies the grid for
marginal benefit; do not build until the higher-TF gate has proven OOS value.

### B.2 Resampling — three correctness details the draft omits

1. **Session-aligned bar origin.** NSE trades 09:15–15:30. Pandas resample
   defaults to clock-hour bins (10:00, 11:00…), while Kite's native 60-minute
   candles align to 09:15 (09:15–10:15, 10:15–11:15…). `resample_ohlcv` must
   use `origin="09:15"` (offset alignment), or the consistency test against
   native candles fails on every bar — and worse, backtest and live would gate
   on differently-phased trends.
2. **Closed-bar rule, precisely:** include a higher-TF bar only if
   `bar_end <= now`. The forming bar is always dropped. This single predicate
   is the look-ahead guarantee; unit-test it at bar boundaries (10:14:59 vs
   10:15:00).
3. **Warm-up depth math:** EMA-50 on 1-hr needs ≥ 50 *closed* hourly bars ≈ 8+
   sessions. Bump the trading-TF fetch depth to ~12 sessions of 15-min candles
   (buffer for holidays/half-days) and reuse the global `WARMUP_CANDLES`
   convention: MTF gate returns "not ready" (→ no veto, or no trade — decide
   explicitly; recommend **no trade**, fail-closed) until warm.

Consistency test vs stored native 1-hr candles: exact match on O/H/L/C bar
boundaries; volume tolerance ±1% (tick aggregation vs exchange aggregation).

### B.3 Veto accounting — measure value, not just frequency
Count of `mtf_veto` is not evidence. For every vetoed signal, persist the full
signal (entry, SL, target) and let the nightly job **replay its counterfactual
outcome** from stored candles: would it have hit SL or target? The weekly
report then states directly: "vetoes avoided ₹X of losses and forfeited ₹Y of
wins" — the only number that decides adoption.

### B.4 Validation (tightened)
- Paired on/off backtest per strategy — same entries minus vetoed ones — over
  the stored year, judged OOS via walk-forward as usual.
- **Cap the initial grid:** 2 rules (`ema_trend`, `supertrend_dir`) × 1 higher
  TF (1hr) × 13 strategies is already 26 paired tests; with sweeps on top,
  false positives are guaranteed at scale. Adopt per strategy only where OOS
  expectancy improves **net of the trade-count reduction** (fewer trades must
  cut costs more than gross), and be suspicious of any strategy where MTF
  helps in-sample but not OOS.
- Autotune/overlay: `mtf_confirm.rule` and `higher_tf` become overlay-tunable
  axes with hard bounds (whitelisted rules/TFs only), same validation as all
  overlay fields.

### B.5 Phases
- B1: `resample_ohlcv` (origin=09:15, closed-bar predicate) + consistency tests
- B2: wrapper + config schema + veto persistence **+ counterfactual replay job**
- B3: paired backtest matrix + capped autotune axes + overlay bounds
- B4: paper enablement of per-strategy winning configs (fail-closed when unwarm)

---

## Part C — Feature interaction (new)

A and B are not independent: scanner picks are high-RVOL movers, whose
higher-TF trend profile differs from sleepy large-caps, so **MTF veto rates and
value will differ between the fixed list and the scanner universe.**

Rules:
1. **Gate order in the cycle:** universe filter → scanner rank → strategy
   signal → MTF veto → risk manager. Each stage logs its rejections.
2. **Freeze one variable at a time.** Validate B on the fixed watchlist first
   (it's testable on the stored year today). Freeze the winning MTF configs.
   Then run A5's cohort comparison *with those frozen configs*, so the
   scanner's go/no-go isn't confounded by simultaneous MTF tuning.
3. Never tune A thresholds and B parameters in the same sweep.

---

## Sequencing (confirmed, one insertion)
1. **A0 immediately** — persistence costs a day and history only accrues in
   real time.
2. **B1–B3** — zero new data dependencies, testable on the stored year this
   week, attacks the known false-breakout failure mode.
3. **A1–A5** — bigger payoff, needs live-market days; runs while B's paper
   phase proceeds.
4. Paper campaign continues unchanged; each piece merges only after backtest +
   walk-forward + (for A) the quantified paper gate.
