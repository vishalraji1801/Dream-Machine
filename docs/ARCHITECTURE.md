# Dream Machine — Architecture & File Guide

An automated NSE equity trading system. It runs a **swing sleeve** (daily signals, CNC/delivery,
held overnight) and an **intraday sleeve** (MIS, square-off before close), gated by a **regime
router**, with a **Strategy Maker** that generates and rigorously validates strategies, a
**backtester/validation** stack, a **paper→live** lifecycle, and a **web control UI**.

Two data stores: `data_cache/backtest_data.db` (historical candles) and `logs/trades.db`
(the live ledger — trades, signals, routing). Kite Connect is the broker/data source.

---

## Top-level layout

```
trading-bot/
├── bot.py                # THE unified CLI — one entry point for the whole lifecycle
├── main.py               # the live/paper trading loop (bot.py run)
├── make.py               # the Strategy Maker CLI  (bot.py make)
├── auth.py               # daily Kite TOTP login    (bot.py auth)
├── backtest_run.py       # multi-strategy/TF backtest (bot.py backtest)
├── validate.py sweep.py autotune.py backfill_profiles.py   # validation / tuning utilities
├── src/                  # the engine (52 modules) — data, strategies, router, execution, risk
├── maker/                # the Strategy Maker funnel (generate → screen → gauntlet → reserve)
├── indicators/           # pinned indicator math (no TA-Lib; golden-fixture tested)
├── strategies/           # per-strategy YAML metadata (regime routing + validation fit)
├── webapp/ + frontend/   # FastAPI backend + React PWA control UI
├── config/               # config.yaml (all knobs), events.yaml, overlay.yaml, .env (secrets)
├── data_cache/           # backtest_data.db (candles), reserve_lock.json, maker DBs
├── logs/                 # trades.db (ledger), swing_state.json (open positions), *.log
├── tests/                # 88 test files (~860 tests)
└── docs/                 # this file, runbook, checklists, specs
```

---

## Root scripts (the CLI)

`bot.py` is the single entry point; it delegates to the scripts below and adds
`status` / `golive` / `gopaper`:

| Script | `bot.py` command | Role |
|--------|------------------|------|
| `bot.py` | — | Unified lifecycle CLI (status, golive, gopaper, + delegates) |
| `main.py` | `bot.py run` | The live/paper trading loop — startup, cycles, both sleeves |
| `auth.py` | `bot.py auth` | Daily Kite login (TOTP), writes `token.txt` |
| `backtest_run.py` | `bot.py backtest` | Multi-strategy, multi-timeframe historical backtest |
| `validate.py` | `bot.py validate` | 5-stage validation pipeline for one strategy |
| `sweep.py` | `bot.py sweep` | Grid-search which parameters held up historically |
| `autotune.py` | `bot.py tune` | Walk-forward auto-tuner → writes the bounded overlay |
| `make.py` | `bot.py make` | Strategy Maker CLI (`generate` / `status`) |
| `backfill_profiles.py` | — | Volume-profile bootstrap/gap-repair (also auto-run by main.py) |

---

## `src/` — the engine

**Lifecycle & ops**
- `logger.py` — centralised logging setup.
- `ops.py` — helpers for the CLI (status formatting, paper↔live mode flag).
- `command_channel.py` — out-of-process control of the running loop (pause/resume/stop).
- `state_store.py` — crash-recovery state.
- `market_calendar.py` — is the market open right now?

**Auth & market data**
- `auth.py` — loads the saved Kite token into a session at startup.
- `data_fetcher.py` — REST market-data fetch (quotes, instruments).
- `data_streamer.py` — live WebSocket tick stream.
- `tick_candle_builder.py` — builds OHLC candles from ticks (keeps bars current without REST).
- `historical_loader.py` — chunked historical candle download (respects Kite per-request caps).
- `candle_cache.py` — day-stamped CSV cache for backtest/sweep data.
- `backtest_store.py` — the SQLite candle store (`backtest_data.db`).
- `timeframe.py` — pure timeframe resampling (e.g. 5min → 15min → day).

**Strategy framework**
- `strategy.py` — the framework: `TradeSignal`, `STRATEGY_REGISTRY`, `generate_signal()`, the
  indicator toolkit (`_atr`, SMA/EMA…), the regime classifier, and the MTF gate. Registers
  the library + the certified maker strategies.
- `strategy_library.py` — the concrete strategy functions (donchian, bb, supertrend, orb,
  the mined catalog…). Each is a pure `fn(symbol, df, cfg) -> TradeSignal`.
- `maker_certified.py` — the 14 reserve-CERTIFIED maker edges, materialized as `maker_<id>`.
- `maker_gauntlet.py` — the 15 gauntlet-survivors that didn't certify, as `mkg_<id>` (backtestable).
- `strategy_meta.py` — loads `strategies/*.yaml` (per-regime validity + fit); enforces
  "unvalidated params are never selectable live".

**Regime router** (decides *which* strategies run *when*)
- `market_state.py` — pure snapshot of the market (trend/vol/breadth features).
- `regime.py` — classifies the state into a regime (STRONG_TREND_UP/…/QUIET/RANGE).
- `router.py` — pure router: given the regime + each strategy's fit, pick active strategies & weights.
- `adaptive_params.py`, `adaptive_bounds.py` — Level-2 regime-scaled params inside hard bounds.
- `drift_audit.py` — Level-3 continuous re-optimization scaffolding.
- `regime_analyst.py` — computes per-regime fit (PF/trades) from history.
- `live_router.py` — drives the router in the **intraday** loop (intraday strategies only).
- `overlay.py` — a bounded, validated parameter sandbox the auto-tuner writes into.

**Universe & selection**
- `universe_builder.py` — builds the tradeable universe (F&O-liquid names, price band ₹100–5000).
- `stock_selector.py` — ranks candidates by turnover (liquidity), keeps top-N.
- `scanner.py` — intraday momentum scanner (ranks the day's movers).

**Execution & risk**
- `order_executor.py` — places/monitors/cancels Kite orders; GTT OCO (stop+target); `modify_gtt`
  for the trailing stop; product override (CNC for swing, MIS for intraday).
- `position_manager.py` — intraday position tracking + trailing SL.
- `risk_manager.py` — position sizing, circuit breakers (max daily loss / trades).
- `paper_trader.py` — simulates fills (paper mode) instead of placing real orders.
- `swing_engine.py` — **the swing sleeve**: once-a-day daily-bar entries/exits, CNC held
  overnight, ATR trailing, capital-aware sizing with **refusal logging**, own persisted book
  (`swing_state.json`), and **live broker reconciliation** (Kite holdings = source of truth) +
  CNC order placement + GTT management.

**Backtest / validation / tuning**
- `backtester.py` — the core event-driven backtest engine (fills, SL/target, trailing, costs).
- `backtest_runner.py` — orchestrates multi-symbol/TF backtests.
- `param_sweep.py` — grid-search parameters over the backtester.
- `validation.py` — the 5-stage validation pipeline.
- `auto_tuner.py` — deterministic walk-forward tune → overlay.
- `router_backtest.py` — backtests the whole router (regime-switching).
- `mtf_replay.py` — multi-timeframe veto counterfactual replay.

**Costs, ledger, persistence, alerts, go-live**
- `costs.py` — Zerodha cost model (MIS intraday + CNC delivery), used by every backtest/fill.
- `trade_db.py` — the SQLite ledger (`trades.db`): trades, signals, routing, snapshots.
- `trade_ledger.py` — higher-level ledger helpers.
- `volume_profile.py`, `profile_store.py` — volume profiles & RVOL (+ persistence).
- `event_calendar.py` — "avoid volatile periods" filter (results/events).
- `go_live.py` — evaluates paper evidence against the go-live gate (used by `bot.py golive`).
- `alert_manager.py`, `telegram_controller.py` — Telegram alerts + remote commands.

---

## `maker/` — the Strategy Maker

Generates candidate strategies from a block grammar and puts each through an honest,
overfitting-resistant funnel. Runs via `bot.py make generate`.

- `blocks.py` — the block library (universe/regime/setup/trigger/exit/hold), each with an
  economic rationale and the ONLY param values the generator may sample.
- `grammar.py` — a `Candidate` = one block per slot; `compile()` snaps it into a pure
  `fn(symbol, df, cfg) -> TradeSignal` the existing backtester runs. Deterministic `cid`.
- `constraints.py` — generation-time rejects (parsimony budget, turnover budget, short-on-CNC,
  the intraday "stocks-in-play required" / falsified-region guard).
- `generate.py` — seeded random sampling over the implemented blocks (swing + intraday whitelists).
- `screen.py` — the cheap first-pass backtest that kills ~90% of candidates; `oos_metrics` =
  the shared warmup-correct walk-forward primitive.
- `vscreen.py` — a vectorized screen for the breakout family (conservative: never flatters).
- `run_gauntlet.py` — the gauntlet: sweep the param neighbourhood (plateau), pick best in-sample,
  test out-of-sample against a rising acceptance bar.
- `reserve.py` — the LOCKED single-shot holdout (RULE 2): a gauntlet survivor gets ONE reserve
  exam per family, ever; PASS → ALIVE. Includes the append-only VOID supersede path.
- `bar.py` — the trial-adjusted acceptance bar `pf_required(N) = 1.2 + 0.15·log10(N/10)`.
- `registry.py` — the append-only trial DB (`maker_trials.db`), DB-trigger-enforced (RULE 1).
- `writer.py` — single-writer queue for the registry.
- `campaign.py` / `parallel_campaign.py` — the end-to-end funnel (serial / process-parallel).
- `admission.py` — paper & portfolio admission (correlation cap).
- `coherence.py` — timeframe-coherence gate. `cache.py` — indicator cache. `data_adjust.py` —
  corporate-action back-adjustment.

---

## `indicators/` — pinned math

Deterministic, TA-Lib-free indicator math with golden-fixture tests, shared by the maker.
- `core.py` — SMA/EMA/Wilder-RSI/ATR/ADX/MACD/Bollinger/Donchian/stochastic.
- `swings.py` — N-bar swing pivots with confirmation lag (no look-ahead).
- `fib.py` — Fibonacci retracement/extension off confirmed pivots.
- `levels.py` — 4-tier support/resistance zones.

## `strategies/` — strategy metadata (YAML)

One `<name>.yaml` per strategy: `regime_param_sets` (which regimes it may run in + params,
`validated: true/false`) and `regime_fit` (measured PF/trades per regime). The router only
selects validated sets with an adequate fit. The 19 maker/gauntlet winners + donchian live here.

## `webapp/` + `frontend/` — the control UI

- `webapp/` — FastAPI backend: `server.py` + `routers/` (auth, control, monitor, logs,
  strategies, backtest, config), `supervisor.py` (starts/stops the bot process), `ws.py`
  (live WebSocket), `sessions.py`, `stores.py`.
- `frontend/` — React/Vite PWA: Dashboard, Positions, Signals, Strategies, Backtest, Controls,
  Settings, Logs, GateChecks, EquityChart. Talks to the webapp over REST + WS.

## `config/`

- `config.yaml` — every knob: trading window, watchlist, risk, costs, regime, scanner,
  universe, `swing:` (capital, position caps), `overlay:`, etc.
- `events.yaml` — event-avoidance calendar. `overlay.yaml` — the auto-tuner's validated overlay.
- `.env` — secrets (Kite/Telegram/etc.), gitignored. `webapp_token.txt` — web UI token.

---

## How the entire workflow works

### A. Data pipeline
`bot.py auth` (TOTP) → session token. **Historical**: `historical_loader` chunks Kite history
into `backtest_data.db` (used by backtests + the maker). **Live**: `data_streamer` streams ticks
→ `tick_candle_builder` forms candles → seeded once via REST, then kept current from ticks.

### B. Strategy creation (the Strategy Maker)
`bot.py make generate` → `generate` samples candidates from `blocks` → `constraints` reject junk
→ `grammar.compile` turns each into a runnable fn → **screen** (cheap kill) → **gauntlet**
(param plateau + OOS vs the rising bar) → **reserve** (one sealed single-shot per family). Every
trial is appended to `maker_trials.db` (RULE 1). Survivors that pass the reserve are ALIVE; they
get materialized into `maker_certified.py`. (This session: swing found real edges; intraday found
none across all 5 timeframes.)

### C. Backtesting & validation
Any registered strategy runs through `backtester.py` (honest fills + `costs.py`).
`backtest_runner`/`param_sweep`/`validation`/`auto_tuner` provide multi-symbol sweeps,
walk-forward, and the pre-capital gate. Signal-level (per-symbol pooled) backtests give the
statistically-conclusive out-of-sample read; the auto-tuner writes only bounds-checked winners
into `overlay.yaml`.

### D. The daily live/paper loop (`bot.py run` → `main.py`)
1. **Startup** — load config + Kite session; build/refresh the universe; init the ledger,
   scanner, regime router (intraday), and the swing engine.
2. **Intraday cycles** (through the session) — `scanner` ranks the day's movers → `live_router`
   classifies the regime and activates intraday strategies → `generate_signal` per name →
   `risk_manager` sizes → `order_executor` (live) or `paper_trader` (paper) executes MIS →
   `position_manager` trails stops → square-off before close.
3. **Swing sleeve** (once, 15:00–15:14) — `swing_engine.run_daily`:
   - **(live) reconcile** against Kite holdings first (Kite = source of truth).
   - **manage exits** on the daily bar: ratchet the ATR trailing stop; (live) MODIFY the GTT.
   - **scan entries**: regime router picks active winners → deploy free capital up to the
     per-position cap; a signal it can't fund a viable position for is **REFUSED and logged**
     (missed-opportunity record). (Live) place the CNC order + a GTT OCO stop/target.
   - persist the book to `swing_state.json`; everything recorded to `trades.db`.
4. **Exits (live)** happen at the exchange via the GTT (anytime, even offline) and are booked at
   the next morning's reconciliation. **Paper** simulates exits on the daily bar.

### E. Paper → live
Run in **paper** first (`bot.py run`, mode=paper) to accumulate real forward evidence. `bot.py
golive` reports whether that evidence clears the objective gate (≥ days/trades, PF, positive net);
`bot.py golive --confirm` flips the mode. Live adds the three execution pieces the swing engine
now has: **reconciliation + CNC order placement + GTT stop management**.

---

*Generated 2026-07-21. Keep it current when modules are added/removed.*
