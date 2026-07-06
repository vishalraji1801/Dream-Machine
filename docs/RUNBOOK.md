# Trading Bot — Operational Runbook

One page for the whole lifecycle. Every command runs from `trading-bot/` using
`.venv\Scripts\python.exe bot.py <command>` (abbreviated to `bot` below).

## The lifecycle at a glance

```
backtest  ──►  validate  ──►  PAPER campaign  ──►  golive gate  ──►  LIVE
(bot backtest)  (bot validate)  (bot run, daily)     (bot golive)     (bot run)
                                                        ▲  │
                                                        │  ▼ anytime
                                                     bot gopaper
```

## 1. Research: backtest & validate

```
bot backtest --offline --no-analyze          # all 13 strategies x 5 TFs on stored data
bot backtest --symbols HDFCBANK,TCS          # online: delta-load fresh data, then run + Claude analysis
bot validate --strategy breakout_retest --days 90 --param br_lookback=15,20,30
```

- Backtest results: `logs/backtest_matrix_*.md` (+ Claude verdict in `logs/ai_review.md`).
- Only a strategy that PASSES the validate.py scorecard (out-of-sample) earns a
  paper campaign. In-sample numbers alone mean nothing.

## 2. Paper campaign (every trading day)

Double-click `start_bot.bat`, or:

```
bot auth        # TOTP prompt (weekend-guarded; --force to override)
bot run         # starts the bot in the mode shown by `bot status`
```

- Paper mode simulates realistic fills; every trade lands in `logs/trades.db`.
- Control from Telegram: `/status`, `/pause`, `/resume`, `/stop`.
- Check progress anytime: `bot status` (shows trades accumulated vs the gate).
- Scheduled Claude agents (post-market/pre-market/weekly) report automatically
  if registered: `.\setup_ai_agents.ps1`.

## 3. Going live

```
bot status                  # gate summary: trades >= 20, days >= 5, PF >= 1.2, ...
bot golive                  # dry-run: prints the full gate report, flips nothing
bot golive --confirm        # flips to LIVE only if the gate PASSES
bot golive --confirm --force  # overrides a failed gate — you own the risk
```

Before confirming, also check `docs/GO_LIVE_CHECKLIST.md` (judgement gate:
paper-vs-backtest divergence, error patterns, capital sizing).

First live week: reduce `risk.total_capital` in config.yaml, watch Telegram.

## 4. Rollback / emergencies

| Situation | Action |
|---|---|
| Stop trading NOW | Telegram `/stop` (squares off everything, exits) |
| Pause new entries only | Telegram `/pause` (positions still managed) |
| Back to paper | `bot gopaper` then restart |
| Bot crashed | watchdog auto-restarts in 15s; state restores same-day |
| GTT fired while bot was down | broker reconciliation books it automatically |

## Command reference

| Command | What it does |
|---|---|
| `bot status` | mode, token freshness, market state, paper progress vs gate |
| `bot auth` | daily Kite login (TOTP only; password from keyring/.env) |
| `bot run` | start the trading loop (mode from config) |
| `bot backtest [...]` | multi-strategy multi-TF backtest (`backtest_run.py` args) |
| `bot validate [...]` | 5-stage statistical validation (`validate.py` args) |
| `bot sweep [...]` | parameter grid sweep (`sweep.py` args) |
| `bot golive [--confirm] [--force]` | gated flip to live |
| `bot gopaper` | instant flip back to paper |
