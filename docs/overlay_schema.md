# AI Overlay Schema (`config/ai_overlay.yaml`)

The scheduled Claude **pre-market strategist** writes this file. The bot loads it at
startup, validates every field against hard bounds in the `ai:` section of
`config.yaml`, and either applies it or rejects the **whole** file and falls back to
`config.yaml` (with a Telegram alert). Claude proposes; deterministic code disposes.

## What an overlay may change

Only these fields are adjustable. Anything else (capital, position caps, circuit
breakers, product type, watchlist, cost model) is **immutable** and will cause the
overlay to be rejected if present.

```yaml
meta:                       # optional, ignored by the bot — for Claude's notes
  written_by: pre-market-strategist
  date: "2026-07-06"
  reasoning_file: logs/ai_decision_2026-07-06.md

strategy:
  name: momentum_vwap_breakout   # must be in ai.allowed_strategies
  rsi_entry_threshold: 60        # 50–80
  volume_multiplier: 1.5         # 1.0–5.0
  regime_filter_enabled: true

risk:
  stop_loss_pct: 1.0             # ai.min_stop_loss_pct … ai.max_stop_loss_pct
  target_pct: 2.0                # ai.min_target_pct … ai.max_target_pct
  trailing_sl_enabled: true
  max_trades_per_day: 8          # 1–20

trading:
  entry_start_time: "09:45"      # within market hours
  entry_end_time: "14:30"        # within market hours
```

## Rules enforced by `src/ai_overlay.py`

1. Unknown section or field → overlay rejected.
2. Any numeric/enum out of the bounds above → overlay rejected.
3. Entry times outside `market_open`…`market_close` → overlay rejected.
4. Unparseable YAML or non-mapping → overlay rejected.
5. Rejection is all-or-nothing: a single bad field discards the entire overlay.

A rejected or missing overlay is safe — the bot simply runs on `config.yaml`.
