"""
Daily universe builder (V2 P3).

Runs pre-market: downloads the NSE instrument dump once, filters to a tradeable
universe (~150-250 liquid MIS-friendly stocks), and writes
data_cache/universe_YYYY-MM-DD.csv. The bot subscribes this whole set on the
WebSocket at startup (one connection carries up to 3,000 instruments).

The core filter is a pure function so it can be unit-tested without Kite. Live
liquidity/turnover metrics need history and are approximated here by an optional
F&O-underlying whitelist (inherently liquid, MIS-friendly) plus a price band.
"""
import csv
import os
from datetime import datetime
from typing import Optional

from src.logger import get_logger

logger = get_logger("universe_builder")


def filter_universe(instruments: list[dict], ltp_map: Optional[dict] = None,
                    cfg: Optional[dict] = None) -> list[dict]:
    """
    instruments: Kite instrument dump rows (dicts with tradingsymbol,
    instrument_token, instrument_type, segment, exchange).
    ltp_map: {tradingsymbol: ltp} for the price-band filter (optional).
    cfg: the `universe:` config section.
    Returns [{symbol, token}] for names that pass all filters.
    """
    cfg = cfg or {}
    ltp_map = ltp_map or {}
    price_min = cfg.get("price_min", 100)
    price_max = cfg.get("price_max", 5000)
    fno = set(cfg.get("fno_underlyings", []))
    exclude = set(cfg.get("exclude", []))

    out = []
    for inst in instruments:
        sym = inst.get("tradingsymbol")
        if not sym or sym in exclude:
            continue
        if inst.get("instrument_type") != "EQ":
            continue
        if inst.get("exchange", "NSE") != "NSE":
            continue
        if fno and sym not in fno:
            continue
        ltp = ltp_map.get(sym)
        if ltp is not None and not (price_min <= ltp <= price_max):
            continue
        out.append({"symbol": sym, "token": inst.get("instrument_token")})
    logger.info(f"Universe filtered to {len(out)} symbols")
    return out


class UniverseBuilder:
    def __init__(self, cfg: dict, cache_dir: str = "data_cache"):
        self._cfg = cfg
        self._u = cfg.get("universe", {})
        self._exchange = cfg["trading"]["exchange"]
        self._cache_dir = cache_dir

    def _path(self, day: Optional[datetime] = None) -> str:
        day = day or datetime.now()
        return os.path.join(self._cache_dir, f"universe_{day:%Y-%m-%d}.csv")

    def build(self, kite) -> list[dict]:
        """Fetch instruments (+ optional LTP snapshot) and write today's universe file."""
        instruments = kite.instruments(self._exchange)
        ltp_map = {}
        try:
            symbols = [f"{self._exchange}:{i['tradingsymbol']}" for i in instruments
                       if i.get("instrument_type") == "EQ"]
            # /quote/ltp allows up to 1000 per request; chunk it
            for chunk_start in range(0, len(symbols), 1000):
                chunk = symbols[chunk_start:chunk_start + 1000]
                data = kite.ltp(chunk)
                for key, v in data.items():
                    ltp_map[key.split(":", 1)[1]] = v.get("last_price")
        except Exception as exc:
            logger.warning(f"LTP snapshot failed ({exc}) — price band skipped")

        universe = filter_universe(instruments, ltp_map, self._u)
        self._write(universe)
        return universe

    def _write(self, universe: list[dict]) -> None:
        os.makedirs(self._cache_dir, exist_ok=True)
        path = self._path()
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["symbol", "token"])
            for row in universe:
                w.writerow([row["symbol"], row["token"]])
        logger.info(f"Universe written: {path} ({len(universe)} symbols)")

    def load_today(self) -> Optional[list[dict]]:
        """Return today's universe file as [{symbol, token}], or None."""
        path = self._path()
        if not os.path.exists(path):
            return None
        with open(path, newline="") as f:
            return [{"symbol": r["symbol"], "token": int(r["token"])}
                    for r in csv.DictReader(f)]
