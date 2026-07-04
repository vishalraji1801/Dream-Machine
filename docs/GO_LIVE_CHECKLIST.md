# Go-Live Checklist (V2 P7)

Going live is a deliberate, manual decision. No script flips
`paper_trading.enabled` for you. Work through this before switching to real money.

## 1. Evidence gate (data-driven)

Run the readiness check:

```
.venv\Scripts\python.exe go_live_check.py
```

It reads paper trades from `logs/trades.db` and reports PASS/FAIL against:

| Criterion | Default requirement |
|---|---|
| Trading days | ≥ 5 distinct paper days |
| Trade count | ≥ 20 paper trades |
| Net P&L (net of costs) | > 0 |
| Profit factor | ≥ 1.2 |
| Win rate | ≥ 45% |

Override any threshold under a `go_live:` section in `config.yaml`.

## 2. Human review (judgement gate)

Even on a PASS, confirm:
- [ ] Paper P&L is **consistent with the backtest expectation** (no large live-vs-backtest divergence in `logs/ai_review.md`).
- [ ] No unresolved ERROR patterns in `logs/structured_*.jsonl`.
- [ ] Broker reconciliation logged no unexplained external exits.
- [ ] The strategy/parameters you're going live with are the ones that were paper-traded (check any active `config/ai_overlay.yaml`).
- [ ] Max daily loss, kill switch, and sector cap are set to values you're comfortable risking.

## 3. Flip to live (manual)

1. In `config/config.yaml` set `paper_trading.enabled: false`.
2. **Start at reduced capital** — lower `risk.total_capital` for the first live week.
3. Watch Telegram closely on day one; `/stop` is always available.
4. Re-run `go_live_check.py` weekly to confirm the edge holds live.

## Rollback

Set `paper_trading.enabled: true` and restart. Open positions are protected by
Kite GTT orders regardless of bot state.
