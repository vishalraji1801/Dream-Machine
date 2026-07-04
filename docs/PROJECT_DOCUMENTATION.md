# Trading Bot V1 — Project Documentation

**An autonomous intraday trading bot for NSE equities, built on Zerodha's Kite Connect API.**

Last updated: 2026-07-04

---

## 1. What This Bot Does

Trading Bot V1 is a fully autonomous intraday trading system. During market hours it:

1. Streams live prices for a 50-stock NIFTY watchlist over a WebSocket.
2. Every cycle, computes technical indicators and looks for a Momentum / VWAP breakout signal.
3. Filters candidates through risk rules (position sizing, margin, spread, market regime, time-of-day).
4. Places entry orders, then protects each position with a Kite-native GTT stop-loss/target that fires server-side even if the bot crashes.
5. Manages open positions (trailing stop-loss, exit on target/SL).
6. Squares off everything at end of day and reports P&L.

It runs in **paper mode** (simulated fills, no real money) or **live mode**, controlled by a single config flag. It can be monitored and controlled entirely from Telegram, survives crashes, and comes with a backtesting engine and parameter sweeper to validate the strategy before risking capital.

---

## 2. Architecture at a Glance

```
                         ┌──────────────┐
                         │   main.py    │  orchestrator: startup, trading
                         │ (run loop)   │  cycle, EOD square-off, shutdown
                         └──────┬───────┘
          ┌─────────────┬───────┼────────┬──────────────┬─────────────┐
          ▼             ▼       ▼        ▼              ▼             ▼
   ┌───────────┐ ┌───────────┐ ┌──────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
   │DataFetcher│ │DataStreamer│ │Strat.│ │RiskMgr   │ │Position  │ │Order/    │
   │(REST)     │ │(WebSocket) │ │egine │ │          │ │Manager   │ │PaperExec │
   └───────────┘ └───────────┘ └──────┘ └──────────┘ └──────────┘ └──────────┘
          │             │                                              │
          ▼             ▼                                              ▼
      Kite REST    KiteTicker                                     Kite orders
      (quotes,     (live ticks)                                   + GTT OCO
      candles)

   Cross-cutting: AlertManager (Telegram out) · TelegramController (Telegram in)
   StateStore (crash recovery) · TradeLedger (CSV journal) · MarketCalendar
   Costs (charge model) · CandleCache (backtest data)
```

**Design principles**
- Every parameter lives in `config/config.yaml` — nothing is hardcoded.
- Credentials live only in `config/.env` (git-ignored, never committed).
- Each module has a single responsibility and a matching test file.
- The `PaperTrader` is a drop-in replacement for the live `OrderExecutor` — the same code path runs in both paper and live mode.

---

## 3. Features (Complete List)

Features are grouped by theme. Each lists the Jira card, the module(s), and what it does.

### 3.1 Core Trading Pipeline

| Feature | Jira | Module | Description |
|---|---|---|---|
| **Kite authentication** | SCRUM-15/16/17 | `auth.py`, `src/auth.py` | Daily login to Kite Connect and access-token management. Now fully automated (see 3.6). |
| **Logging system** | SCRUM-18/19/20 | `src/logger.py` | Rotating daily log files, format `[TIMESTAMP] [LEVEL] [MODULE] — Message`, configurable retention. |
| **Market data fetcher** | SCRUM-21/22/23 | `src/data_fetcher.py` | REST fetch of live quotes and 5-min OHLCV candles from Kite, with retry/backoff. Also extracts bid/ask depth. |
| **Strategy engine** | SCRUM-27/28/29 | `src/strategy.py` | Momentum / VWAP breakout. Computes VWAP, EMA 9/21, RSI 14, Volume SMA 20 and emits BUY/SELL/HOLD signals with entry, SL, and target. |
| **Risk manager** | SCRUM-30/31/32/33 | `src/risk_manager.py` | Pre-trade checks (margin, position count, order size) and daily circuit breakers (loss limit, trade count, consecutive API errors). Position sizing by fixed fractional risk. |
| **Order executor** | SCRUM-34/35/36 | `src/order_executor.py` | Places, monitors, and cancels live Kite orders. |
| **Position manager** | SCRUM-37/38/39 | `src/position_manager.py` | Tracks open positions, monitors SL/target, trailing stop-loss, EOD square-off list. |
| **Scheduler & main loop** | SCRUM-40/41/42/43 | `main.py` | Startup validation, the 5-minute trading cycle, EOD square-off, graceful shutdown. |
| **Telegram alerts** | SCRUM-24/25/26 | `src/alert_manager.py` | Outbound notifications for every meaningful event (see 3.7 for the full list). |

### 3.2 Live Data & Native Protection

| Feature | Jira | Module | Description |
|---|---|---|---|
| **KiteTicker WebSocket streaming** | SCRUM-49/50/51 | `src/data_streamer.py` | Replaces REST polling with a live tick stream (`wss://ws.kite.trade`). Thread-safe tick buffering; the bot falls back to REST automatically if the stream drops or has no ticks yet. |
| **GTT OCO orders** | SCRUM-52/53/54 | `order_executor.py`, `position_manager.py` | Every entry is protected by a Kite-native two-leg GTT (One-Cancels-Other) holding the stop-loss and target. These fire on Kite's servers even if the bot process dies. Trailing-SL updates refresh the GTT. |

### 3.3 Paper Trading

| Feature | Jira | Module | Description |
|---|---|---|---|
| **Paper trading mode** | SCRUM-44/45 | `src/paper_trader.py` | Drop-in replacement for the order executor. Simulates fills at LTP ± slippage, no real orders. Toggled by `paper_trading.enabled`. |
| **Realistic fills** | SCRUM-60 | `paper_trader.py` | With `realistic_fills: true`, a LIMIT order fills only when the live price actually crosses the limit; otherwise it stays OPEN and is treated as unfilled — mirroring real trading. |

### 3.4 Reliability (survives crashes & outages)

| Feature | Jira | Module | Description |
|---|---|---|---|
| **Crash recovery** | SCRUM-62 | `src/state_store.py` | Saves open positions, daily P&L, and trade count to `logs/bot_state.json` every cycle. On a same-day restart it restores them, so circuit breakers and position management survive a crash. |
| **Watchdog auto-restart** | SCRUM-63 | `start_bot.bat` | `main.py` returns exit code 1 on an unhandled crash; the launcher restarts it after 15s. A clean shutdown (`/stop`, Ctrl+C) exits 0 and does not restart. |
| **Heartbeat** | SCRUM-64 | `main.py` | Hourly "alive" Telegram message (open positions, streamer state, P&L). Silence becomes a warning sign. |
| **Broker reconciliation** | SCRUM-76 | `main.py` | Every live cycle, compares bot positions against Kite's actual position book. If a GTT fired server-side or you closed a trade manually in the Kite app, the bot detects it, books the real P&L, logs it, alerts you — and avoids placing a duplicate exit order. Skipped in paper mode. |

### 3.5 Realism & Strategy Quality

| Feature | Jira | Module | Description |
|---|---|---|---|
| **Transaction costs** | SCRUM-65 | `src/costs.py` | Models Zerodha intraday charges (brokerage capped at Rs.20/leg, STT, exchange txn, SEBI, stamp duty, GST). Subtracted from P&L in live exits, EOD square-off, and every backtest trade — so results are net, not gross. |
| **Liquidity guard** | SCRUM-66 | `main.py`, `data_fetcher.py` | Skips entries when the bid-ask spread exceeds `max_spread_pct` (0.15%). Protects against bad fills on illiquid names. |
| **Market regime filter** | SCRUM-67 | `strategy.py`, `backtester.py` | Classifies the NIFTY index as BULLISH / BEARISH / NEUTRAL (index close vs EMA 20 with a neutral band). BUY entries only in BULLISH, SELL only in BEARISH, nothing in NEUTRAL. |
| **Entry time windows** | SCRUM-68 | `main.py`, `backtester.py` | No new entries before 09:45 (opening volatility) or after 14:30 (no time for the move to play out). Open positions are still managed outside the window. |
| **Partial fill handling** | SCRUM-74 | `main.py` | If an entry order fills partially, the bot cancels the remainder, opens the position with the actual filled quantity, sizes the GTT to match, and alerts you. |

### 3.6 Tooling — Backtesting & Optimisation

| Feature | Jira | Module | Description |
|---|---|---|---|
| **Backtesting engine** | SCRUM-57/58/59 | `src/backtester.py`, `backtest.py` | Replays historical candles through the *live* strategy and risk rules (position sizing, SL/target, trailing SL, EOD square-off, circuit breakers). Reports win rate, profit factor, avg win/loss, max drawdown, net P&L. Conservative assumptions: SL assumed to hit before target within a candle; trailing SL uses the previous candle's close (no look-ahead). |
| **Parameter sweep** | SCRUM-69 | `src/param_sweep.py`, `sweep.py` | Grid-searches strategy parameters over the backtester and ranks combinations by net P&L. E.g. `--param rsi_entry_threshold=55,60,65 --param target_pct=1.0,1.5,2.0`. |
| **Backtest data caching** | SCRUM-75 | `src/candle_cache.py` | Day-stamped CSV cache under `data_cache/`. First backtest fetches from Kite; re-runs and sweeps read from cache — dramatically faster and easier on API limits. Cache auto-expires daily. |

### 3.7 Control, Monitoring & Security

| Feature | Jira | Module | Description |
|---|---|---|---|
| **Automated Kite login** | SCRUM-55 | `auth.py` | Headless OAuth using `requests` (no browser). Reads user ID from `.env`, prompts only for TOTP, then starts the bot. `start_bot.bat` is a one-double-click launcher. |
| **Telegram bot control** | SCRUM-56 | `src/telegram_controller.py` | Background thread polling Telegram. `/stop` triggers graceful shutdown; `/status` reports state. Only responds to the authorised chat ID. |
| **Telegram /pause & /resume** | SCRUM-70 | `telegram_controller.py`, `main.py` | `/pause` halts new entries while still managing open positions; `/resume` re-enables. `/status` shows the paused state. |
| **Secure password storage** | SCRUM-71 | `auth.py` | Reads the Zerodha password from Windows Credential Manager (keyring) first, `.env` as fallback. `python auth.py --set-password` stores it securely so it can be removed from `.env`. |
| **Auto-start** | SCRUM-72 | `setup_autostart.ps1` | Registers a weekday 09:00 Windows Task Scheduler job that launches the bot interactively (TOTP prompt on screen). `-Remove` uninstalls it. |
| **Market calendar** | SCRUM-73 | `src/market_calendar.py` | Weekday + market-hours awareness. The main loop idles on weekends; `auth.py` refuses to prompt for TOTP on a weekend (`--force` overrides); `/status` shows OPEN/CLOSED. |

### 3.8 Telegram Alert Types

Outbound events the bot sends (`alert_manager.py`): `bot_started`, `signal_generated`, `order_placed`, `order_filled`, `order_partial`, `order_rejected`, `sl_hit`, `target_hit`, `circuit_breaker`, `daily_summary` (+ per-trade breakdown), `critical_error`, `api_error`, `bot_stopped`, plus raw messages for state restore, heartbeat, and broker reconciliation.

Inbound commands (`telegram_controller.py`): `/stop`, `/pause`, `/resume`, `/status`.

### 3.9 Trade Ledger

| Feature | Jira | Module | Description |
|---|---|---|---|
| **Trade ledger** | SCRUM-61 | `src/trade_ledger.py` | Every closed trade is appended to `logs/trades_YYYY-MM-DD.csv` (symbol, direction, qty, entry/exit price + time, P&L, exit reason). The EOD Telegram summary includes a per-trade breakdown. |

---

## 4. How It Works — Detailed Mechanics

This section explains the actual logic, not just what each part is for.

### 4.1 The Trading Cycle (runs every 5 minutes)

`main.py` runs one `trading_cycle()` per interval. Each cycle:

1. **Circuit-breaker check.** `RiskManager.check_circuit_breakers()` runs first. If the daily loss limit (Rs. 10,000), max trades/day (8), or consecutive API errors (3) is breached, the bot alerts and **skips the entire cycle** — no new management or entries.
2. **Manage open positions** (`_manage_open_positions`):
   - **Broker reconciliation** (live only) runs first — see 4.8.
   - Fetch current quotes (streamer-first, REST fallback — see 4.3).
   - For each open position: update the **trailing stop-loss** (4.6); if it moved, cancel and re-place the GTT with the new SL. Then check **exit conditions** (price ≤ SL or ≥ target for a BUY, mirrored for a SELL). If hit, place a market exit order and clean up.
3. **Scan for entries** (`_scan_entries`), unless paused:
   - Skip entirely if outside the **entry window** (09:45–14:30).
   - Fetch quotes for watchlist symbols not already held.
   - Compute the **market regime** once (4.5). If NEUTRAL, take no entries this cycle.
   - For each candidate: check **bid-ask spread** (skip if > 0.15%), fetch candles, run the **strategy** (4.4). If it returns HOLD, or the signal direction fights the regime, skip. Otherwise compute quantity (4.7), run **pre-trade risk checks**, and if all pass, place the entry.
   - **One entry per cycle** — the loop breaks after the first successful entry to stay within position limits.

### 4.2 Signal Generation — Momentum / VWAP Breakout (`strategy.py`)

On the latest closed candle, the engine computes VWAP, EMA 9, EMA 21, RSI 14, and a 20-period volume SMA, then evaluates:

**BUY** when *all four* hold:
- Close **above VWAP** (intraday strength)
- EMA 9 **crossed above** EMA 21 within the last 3 candles (momentum turn)
- RSI 14 **> 60** (momentum confirmation)
- Volume **≥ 1.5×** its 20-period average (conviction)

**SELL** is the mirror: close below VWAP, EMA 9 crossed below EMA 21, RSI < 40, same volume surge.

On a signal, stop-loss and target are set as fixed percentages of the entry price: **SL = 1%**, **target = 2%** (a 1:2 risk-reward). Anything else is HOLD.

### 4.3 Live Data & Fallback (`data_streamer.py`, `data_fetcher.py`)

The bot subscribes to a KiteTicker WebSocket and buffers ticks per instrument in a thread-safe dict. `_get_quotes()` returns streamer data **only if** the socket is connected *and* has buffered ticks; otherwise it transparently falls back to REST `get_quotes()`. REST quotes also carry bid/ask depth (used by the liquidity guard); streamer quotes don't, so the spread check simply passes when depth is absent.

### 4.4 GTT OCO — the Server-Side Safety Net (`order_executor.py`)

After an entry fills, the bot places a **two-leg GTT (One-Cancels-Other)** on Kite's servers holding both the stop-loss and the target. Because it lives on Kite, it fires **even if the bot process dies**. Trigger ordering depends on direction:
- **BUY** position → exit transaction is SELL, `trigger_values = [stop_loss, target]` (lower = SL, upper = target)
- **SELL** position → exit transaction is BUY, `trigger_values = [target, stop_loss]`

When the trailing SL advances, the bot cancels the old GTT and places a fresh one so the server-side protection always reflects the current stop.

### 4.5 Market Regime Filter (`strategy.market_regime`)

The NIFTY 50 index is classified against its own EMA 20 with a 0.1% neutral band: close above the band → **BULLISH**, below → **BEARISH**, inside → **NEUTRAL**. Entries are gated — BUY only in BULLISH, SELL only in BEARISH, nothing in NEUTRAL. If index data is unavailable the filter "fails open" (entries allowed) rather than blocking trading.

### 4.6 Trailing Stop-Loss (`position_manager.update_trailing_sl`)

Trailing activates once a position is **1% in profit**, then ratchets in **0.5% steps**. For a BUY, `new_sl = entry × (1 + steps × 0.5%)`, floored at the entry price (so it can only lock in gains, never loosen). It never moves backward. Each advance triggers a GTT refresh (4.4).

### 4.7 Position Sizing & Pre-Trade Gates (`risk_manager.py`)

**Sizing** is fixed-fractional: risk per share = |entry − SL|; max risk per trade = 1% of capital (Rs. 5,000); `qty = max_risk / risk_per_share`, then capped so position value ≤ 20% of capital (Rs. 100,000).

**Pre-trade checks** (all must pass): not halted, order value ≤ Rs. 120,000 cap, order value ≤ max position size, open positions < 3, available margin ≥ Rs. 25,000.

### 4.8 Broker Reconciliation (`main.py._reconcile_positions`, live only)

At the start of every live cycle, the bot pulls Kite's day position book and compares each internal position. If the broker shows the position **flat** (quantity 0) — meaning a GTT fired server-side or you closed it manually in the Kite app — the bot removes it internally, books P&L from the broker's buy/sell averages minus costs, writes an `external_exit` ledger row, and alerts you. This is what **prevents a duplicate exit order**. A quantity mismatch (partial external close) raises a manual-review alert instead.

### 4.9 Crash Recovery (`state_store.py`)

Every cycle, open positions + daily P&L + trade count are written atomically to `logs/bot_state.json`, stamped with the date. On startup, if a **same-day** state file exists, the bot restores positions and counters (so circuit breakers stay honest) and alerts you. A stale (previous-day) file is ignored. Combined with the watchdog, a crash costs at most one cycle.

### 4.10 Paper Fills (`paper_trader.py`)

`PaperTrader` mirrors the `OrderExecutor` interface. With `realistic_fills: true`, a LIMIT order fills **only if the live LTP has crossed the limit** (BUY: LTP ≤ limit; SELL: LTP ≥ limit); otherwise it stays OPEN and is treated as unfilled. MARKET orders always fill at LTP ± slippage. GTTs are tracked as fake integer IDs. No real orders ever leave the process.

### 4.11 Backtester Mechanics (`backtester.py`)

The backtester walks every candle chronologically across all symbols and applies the *same* rules as the live bot. Key modelling choices (all conservative):
- **Entry** fills at the signal candle's close (mirrors a LIMIT on the completed candle).
- **Exits** check each candle's high/low against SL and target; if both fall inside one candle, **SL is assumed to hit first**.
- **Trailing SL** advances on the *previous* candle's close — no look-ahead.
- EOD square-off, daily circuit breakers, and per-day counter resets all apply. Costs (4.12) are subtracted per trade, so reported P&L is net.

### 4.12 Transaction-Cost Model (`costs.py`)

For each round trip: brokerage 0.03% per leg capped at Rs. 20; STT 0.025% on the sell leg; NSE exchange txn 0.00297% and SEBI 0.0001% on turnover; stamp duty 0.003% on the buy leg; GST 18% on (brokerage + exchange + SEBI). This is subtracted from P&L in live exits, EOD square-off, broker reconciliation, and every backtest trade.

---

## 5. Configuration Reference (`config/config.yaml`)

| Section | Key settings |
|---|---|
| **trading** | exchange (NSE), product (MIS), 50-symbol watchlist, `timeframe: 5minute`, market hours, `square_off_time: 15:15`, `entry_start_time: 09:45`, `entry_end_time: 14:30` |
| **strategy** | EMA 9/21, RSI 14 (`rsi_entry_threshold: 60`), Volume SMA 20 (`volume_multiplier: 1.5`), regime filter (NIFTY 50, EMA 20, 0.1% band) |
| **risk** | `total_capital: 500000`, `max_risk_per_trade_pct: 1.0`, `max_open_positions: 3`, `order_value_cap: 120000`, `stop_loss_pct: 1.0`, `target_pct: 2.0`, trailing SL, `max_daily_loss: 10000`, `max_trades_per_day: 8`, `max_spread_pct: 0.15` |
| **costs** | Zerodha intraday charge model (brokerage, STT, exchange, SEBI, stamp, GST) |
| **scheduler** | `cycle_interval_seconds: 300`, `heartbeat_interval_minutes: 60` |
| **paper_trading** | `enabled: true`, `simulated_slippage_pct: 0.05`, `realistic_fills: true` |
| **logging** | level, retention_days |

**Going live:** set `paper_trading.enabled: false`. That is the only switch between simulation and real orders.

---

## 6. How to Run

All commands run from the `trading-bot/` folder using the venv Python.

### Daily live/paper run
```
start_bot.bat                          # double-click, or:
.venv\Scripts\python.exe auth.py       # authenticate (enter TOTP)
.venv\Scripts\python.exe main.py       # start the bot
```
Kite tokens expire every morning, so `auth.py` runs each day. On weekends use `auth.py --force`.

### One-time security setup (recommended)
```
.venv\Scripts\python.exe auth.py --set-password   # store password in Credential Manager
# then remove ZERODHA_PASSWORD from config/.env
```

### One-time auto-start setup (optional)
```
.\setup_autostart.ps1            # register weekday 09:00 launch
.\setup_autostart.ps1 -Remove    # undo
```

### Backtesting
```
.venv\Scripts\python.exe backtest.py --days 30
.venv\Scripts\python.exe backtest.py --days 30 --symbols RELIANCE,TCS
.venv\Scripts\python.exe backtest.py --days 30 --no-cache
```

### Parameter sweep
```
.venv\Scripts\python.exe sweep.py --days 30 --param rsi_entry_threshold=55,60,65 --param target_pct=1.0,1.5,2.0
```

---

## 7. Backtest Findings (30 days: 2026-06-04 → 2026-07-03)

**Baseline (current config, 5-min, full watchlist, net of costs):**

| Metric | Value |
|---|---|
| Trades | 59 |
| Win rate | 52.5% |
| Net P&L | Rs. 4,894 |
| Profit factor | 1.31 |
| Max drawdown | Rs. 3,753 |
| Est. costs | Rs. 4,834 |

**Key takeaways:**
1. **The edge is real but thin** — transaction costs consumed ~50% of gross profit.
2. **Current parameters are already near-optimal** in the tested grid; loosening the RSI threshold to 55 is clearly destructive.
3. **Timeframe matters a lot** — 1-min, 15-min, and 30-min all *lost* money on this window; only 5-min (best absolute net) and 1-hr (best risk-adjusted: profit factor 1.51, lower drawdown, half the cost drag) were profitable.

**Caveats:** small sample (25–59 trades), a single month, and coarser timeframes have weaker fill realism. The 5-min vs 1-hr question is best settled by paper-trading both rather than more single-window backtests.

---

## 8. Test Coverage

- **19 source modules**, each with a dedicated test file (**21 test files**).
- **~345 tests passing**, 2 skipped.
- Run the suite: `.venv\Scripts\pytest.exe -q`

---

## 9. Security & Data Handling

- Credentials (`KITE_*`, `ZERODHA_*`, `TELEGRAM_*`) live only in `config/.env`, which is git-ignored. The Zerodha password can be moved to Windows Credential Manager.
- `token.txt` (daily access token) and `data_cache/` are git-ignored.
- Telegram control commands are honoured only from the single authorised chat ID.
- GTT OCO orders provide a server-side safety net independent of the bot process.

---

## 10. Source Tree

```
trading-bot/
├── auth.py                 # daily Kite login (automated, TOTP-only)
├── main.py                 # bot entry point & trading loop
├── backtest.py             # backtest CLI
├── sweep.py                # parameter sweep CLI
├── start_bot.bat           # launcher with watchdog auto-restart
├── setup_autostart.ps1     # Task Scheduler registration
├── config/
│   ├── config.yaml         # all tunable parameters
│   ├── .env                # secrets (git-ignored)
│   └── .env.template       # secrets template
├── src/
│   ├── auth.py             # token loader / session
│   ├── logger.py           # rotating logs
│   ├── data_fetcher.py     # REST quotes & candles
│   ├── data_streamer.py    # KiteTicker WebSocket
│   ├── strategy.py         # signals + market regime
│   ├── risk_manager.py     # risk rules & sizing
│   ├── order_executor.py   # live orders + GTT OCO
│   ├── paper_trader.py     # simulated fills
│   ├── position_manager.py # position tracking
│   ├── alert_manager.py    # Telegram outbound
│   ├── telegram_controller.py # Telegram inbound (/stop /pause /resume /status)
│   ├── state_store.py      # crash recovery
│   ├── trade_ledger.py     # CSV trade journal
│   ├── costs.py            # transaction-cost model
│   ├── market_calendar.py  # is-market-open
│   ├── backtester.py       # backtest engine
│   ├── param_sweep.py      # grid search
│   └── candle_cache.py     # backtest data cache
├── tests/                  # 21 test files, ~345 tests
├── logs/                   # daily logs, trade CSVs, bot_state.json
└── data_cache/             # cached backtest candles (git-ignored)
```

---

## 11. Open Items & Next Steps

- **Verify the strategy over a longer window** (60–90 days) before committing to 5-min vs 1-hr.
- **Paper-trade for a full week** (SCRUM-46/47/48) and review the trade ledger.
- **Go live** only after paper results and costs look acceptable — flip `paper_trading.enabled: false`.
- Not yet built (deferred): NSE holiday calendar, walk-forward validation, web dashboard, multiple concurrent strategies.

---

## 12. Jira Card Index

| Cards | Theme |
|---|---|
| SCRUM-5 … 14 | Project epic & setup |
| SCRUM-15 … 43 | Core bot: auth, logging, data, strategy, risk, orders, positions, main loop |
| SCRUM-44 … 48 | Paper trading mode & 5-day run |
| SCRUM-49 … 54 | KiteTicker streaming & GTT OCO |
| SCRUM-55 / 56 | Automated login & Telegram control |
| SCRUM-57 … 61 | Backtester, realistic fills, trade ledger |
| SCRUM-62 … 64 | Crash recovery, watchdog, heartbeat |
| SCRUM-65 / 66 | Transaction costs, liquidity guard |
| SCRUM-67 … 69 | Regime filter, entry windows, parameter sweep |
| SCRUM-70 … 72 | Pause/resume, keyring, auto-start |
| SCRUM-73 … 76 | Market calendar, partial fills, candle cache, broker reconciliation |

All development is tracked in Jira (project SCRUM) and version-controlled on GitHub (`vishalraji1801/Dream-Machine`), with the working branch `develop`.
