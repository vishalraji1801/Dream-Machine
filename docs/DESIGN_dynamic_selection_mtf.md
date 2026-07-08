# Design Draft — Condition-Based Stock Selection & Multi-Timeframe Confirmation

Status: DRAFT for review · 2026-07-08 · builds on V2 P3 (dormant scanner) and the
strategy registry. Goal: one implementation of each idea, reused identically in
**backtest, paper, and live** — the only differences between modes stay where they
are today (order execution + margin source).

---

## Part A — Stop trading a fixed list: condition-based stock selection

### The problem
The bot watches the same 50 NIFTY names regardless of market conditions. On any
given day most of them are dead (no volume, no range) while the day's real movers
— where momentum strategies actually earn — sit outside the list. The 1-yr
backtest quantified the cost: breakout/momentum edges on quiet large-caps are
smaller than transaction costs.

### What already exists (built, opt-in, unvalidated)
- `universe_builder.py` — daily pre-market filter (EQ series, price band, F&O pool)
- `scanner.py` — per-cycle ranking by %-change, range position, gap
- `tick_candle_builder.py` — candles from WebSocket ticks (no REST bottleneck)
- `stock_selector.py` — turnover + ATR% quality filters (used by backtesting)
- Wiring in `_scan_entries` behind `universe.enabled: false`

### What's missing (the actual work)
1. **RVOL — the "something is happening" signal.** The scanner ranks by raw
   %-change; the plan calls for relative volume vs the time-of-day-adjusted
   20-day average. Universe builder must persist per-symbol avg-volume profiles
   (it already fetches 30d daily candles in `stock_selector`); scanner consumes
   them from the daily universe file.
2. **Candle seeding for scanner picks.** When a symbol enters the shortlist
   mid-day, the strategy needs history. Rule: seed from `tick_candle_builder`
   (running since open on the whole universe); REST `get_candles` only as
   fallback for the day's first shortlist.
3. **Point-in-time backtesting.** A dynamic universe backtested on *today's*
   list = survivorship bias. Fixes, in order of availability:
   - persist `universe_YYYY-MM-DD.csv` + scanner rankings daily from day one
     (rankings already land in trades.db) → they become backtest inputs;
   - until enough history accumulates, backtest on the full stored pool with the
     scanner simulated per-bar from stored candles (RVOL/range computable
     offline);
   - `Backtester.run(candles, universe_by_day=...)` restricts entries per day.
4. **Safety rails for live:** cap scanner churn (a symbol must hold rank for 2
   cycles before tradeable), circuit-band exclusion, spread check via REST quote
   on the top-N only (500-symbol quote limit respected).

### Mode-by-mode
| Mode | Behavior |
|---|---|
| Backtest | `backtest_run.py --universe`: per-bar scanner simulation over the stored pool; per-day universe files once they exist |
| Paper | flip `universe.enabled: true`; stream full universe (≤3,000 ok); scanner top-30 traded; rankings audited weekly by the Claude agent |
| Live | identical code path; gate: ≥2 paper weeks where scanner-picked trades ≥ watchlist baseline |

### Phases (Jira-ready)
- A1: RVOL profiles in universe builder + scanner RVOL scoring (+ offline scanner simulation for backtests)
- A2: candle seeding via tick_candle_builder in the live scan path
- A3: backtester `universe_by_day` support + `--universe` mode in backtest_run
- A4: paper enablement + churn/circuit rails + weekly scanner audit
- A5: comparison report (scanner picks vs fixed watchlist, same period) → go/no-go

---

## Part B — Multi-timeframe (MTF) confirmation

### The problem
Every strategy today sees exactly one timeframe (15min). Classic failure: a
clean 15-min breakout that is just noise inside a 1-hr downtrend. Real desks
confirm: **trend on the higher timeframe, signal on the trading timeframe,
timing (optional) on the lower one.**

### Design — one gate, not thirteen rewrites
Add a *confirmation layer* in front of any registered strategy (composition, so
all 13 strategies get MTF for free):

```yaml
strategy:
  name: supertrend
  mtf_confirm:
    enabled: true
    higher_tf: "1hr"        # trend gate timeframe
    rule: "ema_trend"       # ema_trend | supertrend_dir | regime
    ema: 50                 # rule parameter
    # optional finer-TF timing gate (phase 2)
    lower_tf: null
```

Flow in `generate_signal` (wrapper):
1. Run the named strategy on the trading TF → BUY/SELL/HOLD as today.
2. If BUY/SELL and `mtf_confirm.enabled`: compute the trend on `higher_tf`
   (EMA-50 slope/side, or supertrend direction). Signal must AGREE or → HOLD
   with reason `mtf_veto` (logged + counted in trades.db, so we can measure how
   often the veto helps).

### The data problem, solved once: **resampling**
Higher-TF candles are derived by resampling the trading-TF frame
(`15min → 1hr` = standard OHLCV aggregation). One helper `resample_ohlcv(df, tf)`
serves all three modes:
- **Backtest**: resample the stored frame in-window → zero extra data, zero
  look-ahead (resample only *closed* higher-TF bars).
- **Paper/Live**: same resample on the fetched 15-min frame (fetch depth bumped
  to cover ~50 higher-TF bars); no extra API calls, no rate-limit cost.
- 1-min data in the backtest store lets us validate the resampler against
  Kite's native 1-hr candles (consistency test).

### Validation before adoption
MTF is a hypothesis, not a free win (it cuts trade count — costs per remaining
trade must fall more than gross falls). It goes through the same gauntlet:
1. Backtest matrix with `mtf_confirm` on/off per strategy (paired comparison)
2. `bot tune` grid gains `mtf_confirm.rule` / `higher_tf` axes (overlay bounds
   extended accordingly)
3. Only an OOS-passing MTF config reaches paper.

### Phases (Jira-ready)
- B1: `resample_ohlcv` helper + closed-bar semantics + consistency tests vs stored native TFs
- B2: MTF confirmation wrapper + config schema + `mtf_veto` accounting
- B3: backtest matrix paired on/off comparison + autotune axes + overlay bounds
- B4: paper enablement of the winning MTF config

---

## Sequencing recommendation
1. **B1–B3 first** (multi-timeframe): smaller, zero new data dependencies,
   directly attacks the known failure mode (false breakouts on quiet stocks),
   and measurably testable on the existing year of stored data this week.
2. **A1–A5 second**: bigger payoff but needs live-market days to validate the
   scanner and accumulate point-in-time universe history — start persisting
   universe files NOW (A1) so history accrues while B ships.
3. The paper campaign keeps running unchanged throughout; each piece merges only
   after passing backtest + walk-forward.
