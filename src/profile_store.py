"""
Volume-profile persistence (SCRUM-110 / A1, deliverable 2).

One human-inspectable JSON per symbol under data_cache/profiles/. Separated from
the pure `volume_profile` module so that module stays I/O-free.
"""
import json
import os
from datetime import date
from typing import Optional

from src.logger import get_logger
from src.volume_profile import VolumeProfile

logger = get_logger("profile_store")


class ProfileStore:
    def __init__(self, directory: str = os.path.join("data_cache", "profiles")):
        self._dir = directory

    def _path(self, symbol: str) -> str:
        safe = symbol.replace(" ", "_").replace("&", "and").replace("/", "_")
        return os.path.join(self._dir, f"{safe}.json")

    def save(self, profile: VolumeProfile) -> None:
        os.makedirs(self._dir, exist_ok=True)
        doc = {
            "symbol": profile.symbol,
            "bucket_minutes": profile.bucket_minutes,
            "buckets": profile.buckets,
            "sessions_used": profile.sessions_used,
            "last_session": profile.last_session.isoformat(),
            "config_version": profile.config_version,
            "session_dates": [d.isoformat() for d in profile.session_dates],
        }
        with open(self._path(profile.symbol), "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2)

    def load(self, symbol: str) -> Optional[VolumeProfile]:
        path = self._path(symbol)
        if not os.path.exists(path):
            return None
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(f"profile load failed for {symbol}: {exc}")
            return None
        return VolumeProfile(
            symbol=d["symbol"], bucket_minutes=d["bucket_minutes"], buckets=d["buckets"],
            sessions_used=d["sessions_used"], last_session=date.fromisoformat(d["last_session"]),
            config_version=d["config_version"],
            session_dates=tuple(date.fromisoformat(x) for x in d.get("session_dates", [])))

    def sessions_present(self, symbol: str) -> set:
        p = self.load(symbol)
        return set(p.session_dates) if p else set()
