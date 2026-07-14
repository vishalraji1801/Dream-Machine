# A1 Implementation Spec — Volume Profiles & RVOL (for Claude Code)

Implement this spec in the commit sequence at the bottom, one commit per step,
run tests after each.

---

## Context (read first)

- Repo: NSE intraday trading bot (Kite Connect, Python). Relevant modules:
  `universe_builder.py`, `scanner.py`, `tick_candle_builder.py`,
  `stock_selector.py`, `data_streamer.py`, SQLite ledger `trades.db`,
  file cache under `data_cache/`.
- **Design invariant (do not violate):** core logic is pure and mode-blind.
  New computation modules take data in, return values out — no Kite imports,
  no `datetime.now()`, no file I/O inside pure modules. Live/paper/backtest
  differ only via injected providers.
- **Goal:** time-of-day-adjusted relative volume (RVOL) for the scanner.
  RVOL(t) = today's cumulative volume at time t ÷ 20-session average
  cumulative volume at the same time-of-day. Profiles are **bootstrapped once
  via REST**, then **maintained from the tick-built candle archive** (the
  WebSocket already streams the whole universe; ticks carry day-cumulative
  `volume_traded`). REST remains only as a gap-repair path.

## Deliverable 1 — `volume_profile.py` (pure module, no I/O, no Kite)

```python
@dataclass(frozen=True)
class VolumeProfile:
    symbol: str
    bucket_minutes: int                  # 15
    buckets: dict[str, float]            # "09:30" -> avg cumulative volume at that boundary
    sessions_used: int                   # how many sessions contributed
    last_session: date                   # most recent session included
    config_version: str                  # hash of rvol config params

def build_profile(sessions: dict[date, pd.DataFrame], cfg: RvolConfig) -> VolumeProfile | None
    # sessions: per-session 15-min OHLCV frames (session-local, 09:15–15:30).
    # Uses the most recent cfg.window_sessions sessions; returns None if
    # fewer than cfg.min_sessions are available.

def roll_profile(existing: VolumeProfile, new_session: date,
                 candles: pd.DataFrame, cfg: RvolConfig) -> VolumeProfile
    # Adds one session, drops the oldest beyond window_sessions. Idempotent:
    # rolling the same session twice must not double-count.

def rvol(profile: VolumeProfile | None, cum_vol_now: float,
         now: datetime, cfg: RvolConfig) -> float | None
    # Linear interpolation between bucket boundaries for intra-bucket `now`.
    # Returns None if: profile is None, profile.last_session is more than
    # cfg.staleness_sessions trading days before `now`, `now` is before the
    # first bucket boundary, or the interpolated denominator is 0.
```

Rules:
- Cumulative volume per bucket is computed from candle volumes summed from
  session open; the profile stores the **average across sessions** at each
  boundary.
- Half days (e.g., Muhurat): sessions whose last candle ends before 15:30
  still contribute to the buckets they have; missing tail buckets simply get
  fewer contributing sessions. Never zero-fill.
- Suspended/no-trade sessions for a symbol: skip the session entirely (it does
  not count toward `sessions_used`).
- `now` is always a parameter. Never call `datetime.now()`.

## Deliverable 2 — `profile_store.py` (persistence)

- Store one file per symbol under `data_cache/profiles/{SYMBOL}.json`
  (schema: the `VolumeProfile` fields; keep it human-inspectable).
- `load(symbol) -> VolumeProfile | None`, `save(profile)`,
  `sessions_present(symbol) -> set[date]` (for gap detection).
- Also write the current profile snapshot (buckets + last_session) into the
  daily universe file produced by `universe_builder.py`, so the scanner reads
  one file, not two hundred.

## Deliverable 3 — `backfill_profiles.py` (REST bootstrap + gap repair, CLI)

- `python backfill_profiles.py [--symbols X,Y] [--dry-run]`
- For each pool symbol: compute missing sessions =
  (last `window_sessions` trading days) − `sessions_present(symbol)`;
  if empty → skip (this is what makes re-runs idempotent).
- Fetch 15-min candles for the missing date range in **one historical REST
  call per symbol**; throttle to 2.5 req/s with exponential backoff on 429s.
- `--dry-run` prints the fetch plan (symbol → missing sessions → call count)
  without calling the API.
- Log a summary: symbols fetched / skipped / failed, total calls, elapsed.

## Deliverable 4 — EOD roll-forward hook (the WebSocket-derived path)

- In the existing end-of-day job: for each universe symbol, load today's
  15-min candles from the **tick-built candle archive** and call
  `roll_profile`. On success, save.
- If the archive is missing today's session for a symbol (bot down, stream
  gap): do NOT roll; record the symbol+date in a `profile_gaps` list that
  `backfill_profiles.py` picks up on its next run. Fail toward "stale and
  excluded", never toward silently wrong data.

## Deliverable 5 — Scanner integration

- `scanner.py` reads profiles from the daily universe file and adds an `rvol`
  component to the ranking score (weight in config).
- If `rvol()` returns None for a symbol → the symbol is **ineligible for the
  shortlist** this cycle (do not rank it on partial factors). Log exclusion
  reason `rvol_unavailable` to the rankings persisted in `trades.db`.
- Persist the computed rvol value with each ranking row (all symbols, every
  cycle — full rankings, not just top-N).

## Deliverable 6 — Offline scanner simulation (backtest parity)

- The backtest-mode scanner must call the **same** `build_profile`/`rvol`
  functions, with profiles constructed only from sessions **strictly before**
  the replay day (point-in-time; no same-day data in the denominator).
- Add `--universe` plumbing only if it is not already present from A3; this
  deliverable is the RVOL part, not the whole universe replay.

## Config additions (`config.yaml`)

```yaml
universe:
  rvol:
    bucket_minutes: 15
    window_sessions: 20
    min_sessions: 10
    staleness_sessions: 3
    score_weight: 0.4      # scanner ranking weight; other factors renormalize
```

Compute `config_version` as a hash of this block and stamp it on every profile
and every persisted ranking row.

## Tests (write them; they are the acceptance criteria)

1. **Golden profile:** fixed 3-session candle fixture → exact expected bucket
   values (assert to 6 decimal places; this fixture must never change).
2. **Rolling window:** rolling session 21 drops session 1;
   `sessions_used == window_sessions`. Rolling the same session twice is a
   no-op (idempotency).
3. **Interpolation:** rvol at 10:07 lies between the 10:00 and 10:15 bucket
   implications; exact value asserted from the fixture.
4. **Point-in-time:** profile built "as of day D" contains no day-D data —
   construct a fixture where including day D would change the value, assert it
   does not.
5. **Staleness:** last_session 4 trading days old with
   `staleness_sessions: 3` → `rvol()` returns None.
6. **Half day:** session ending 13:00 contributes to morning buckets only;
   afternoon bucket averages unaffected by it.
7. **Min sessions:** 9 sessions with `min_sessions: 10` → `build_profile`
   returns None; scanner marks `rvol_unavailable`.
8. **Gap repair plan:** store with sessions {D-3, D-1} present and window
   covering D-5..D-1 → dry-run plan requests exactly {D-5, D-4, D-2}.

## Non-goals / hard constraints

- **No REST calls anywhere in the live per-cycle path.** REST exists only in
  `backfill_profiles.py` (scheduled/manual) and existing seeding paths.
- No changes to `strategy.py` or `risk_manager.py` in this ticket.
- No look-ahead: nothing computed for day D may read day-D data into a profile.
- `volume_profile.py` must import neither `kiteconnect` nor anything from the
  bot's I/O layers (enforce with a unit test that inspects imports if easy).
- Do not delete or bypass the ±1% tick-vs-official volume tolerance note —
  RVOL is a ranking signal, not an accounting figure.

## Commit sequence (one commit each, tests green after every step)

1. `volume_profile.py` + tests 1–7 (pure logic only).
2. `profile_store.py` + gap detection + test 8.
3. `backfill_profiles.py` CLI with --dry-run (verify plan output manually).
4. EOD roll-forward hook + `profile_gaps` handoff.
5. Scanner integration + rankings persistence (`rvol`, exclusion reasons).
6. Backtest-mode point-in-time wiring + an end-to-end test on one stored week.

## Definition of done

- All 8 tests pass; full suite green.
- `backfill_profiles.py --dry-run` on the current pool prints a sane plan;
  a real run completes in ~2 minutes and is a no-op when re-run.
- One paper session shows rvol values and `rvol_unavailable` exclusions in the
  persisted rankings in `trades.db`.
- A backtest replay of one stored week produces rvol rankings using only
  prior-session profiles (spot-check one symbol by hand).
