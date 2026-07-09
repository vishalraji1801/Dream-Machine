"""
Volume-profile bootstrap / gap-repair (SCRUM-110 / A1, deliverable 3).

Fetches the missing sessions for each pool symbol (idempotent: re-running is a
no-op once profiles are current) and rebuilds their volume profiles. This is the
ONLY REST path for RVOL — steady-state maintenance is the EOD roll-forward from
tick-built candles. Run it nightly or manually, never in the per-cycle path.

Usage:
  python backfill_profiles.py [--symbols X,Y] [--dry-run]
"""
import argparse
import os
import time
from datetime import date, datetime, timedelta

import yaml
from dotenv import load_dotenv

from src.auth import load_kite_session
from src.data_fetcher import DataFetcher
from src.logger import get_logger, setup_logging
from src.profile_store import ProfileStore
from src.volume_profile import RvolConfig, build_profile

logger = get_logger("backfill_profiles")


def _recent_trading_days(n: int, end: date) -> list:
    days, cur = [], end
    while len(days) < n:
        if cur.weekday() < 5:
            days.append(cur)
        cur -= timedelta(days=1)
    return sorted(days)


def plan(store: ProfileStore, symbols: list, cfg: RvolConfig, end: date) -> dict:
    """symbol -> missing session dates (idempotency: empty means skip)."""
    wanted = set(_recent_trading_days(cfg.window_sessions, end))
    return {s: sorted(wanted - store.sessions_present(s)) for s in symbols}


def main() -> int:
    ap = argparse.ArgumentParser(description="Bootstrap / gap-repair RVOL volume profiles")
    ap.add_argument("--symbols", default="")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    load_dotenv(dotenv_path=os.path.join("config", ".env"))
    with open(os.path.join("config", "config.yaml")) as f:
        cfg_all = yaml.safe_load(f)
    setup_logging(level=cfg_all["logging"]["level"], retention_days=cfg_all["logging"]["retention_days"])
    rcfg = RvolConfig(**cfg_all.get("universe", {}).get("rvol", {}))

    symbols = ([s.strip().upper() for s in args.symbols.split(",") if s.strip()]
               or (cfg_all["universe"].get("fno_underlyings") or cfg_all["trading"]["watchlist"]))
    store = ProfileStore()
    today = datetime.now().date()
    missing = plan(store, symbols, rcfg, today)

    to_do = {s: days for s, days in missing.items() if days}
    total_calls = len(to_do)   # one historical call per symbol covering its range
    print(f"Backfill plan: {len(to_do)}/{len(symbols)} symbols need data, "
          f"~{total_calls} REST calls.")
    for s, days in list(to_do.items())[:10]:
        print(f"  {s}: {len(days)} missing sessions ({days[0]}..{days[-1]})")
    if args.dry_run:
        print("(dry run — no API calls)")
        return 0
    if not to_do:
        print("All profiles current — nothing to do.")
        return 0

    kite = load_kite_session()
    fetcher = DataFetcher(kite, cfg_all)
    fetcher.load_instruments(list(to_do))
    fetched = failed = 0
    for sym, days in to_do.items():
        span = (today - days[0]).days + 2
        try:
            df = fetcher.get_candles(sym, lookback_days=span)   # note: 15min per config
            if df is None or df.empty:
                failed += 1
                continue
            sessions = {d: g for d, g in _split_sessions(df)}
            profile = build_profile(sessions, rcfg)
            if profile:
                store.save(profile)
                fetched += 1
        except Exception as exc:
            logger.warning(f"backfill {sym} failed: {exc}")
            failed += 1
        time.sleep(0.4)   # ~2.5 req/s
    print(f"Done: {fetched} profiles built, {failed} failed.")
    return 0


def _split_sessions(df):
    import pandas as pd
    d = df.copy()
    d["timestamp"] = pd.to_datetime(d["timestamp"])
    d["day"] = d["timestamp"].dt.date
    for day, g in d.groupby("day"):
        yield day, g.drop(columns=["day"])


if __name__ == "__main__":
    raise SystemExit(main())
