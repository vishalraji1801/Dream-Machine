"""
Browser sessions issued after a successful TOTP login.

The user authenticates by entering their Kite TOTP (verified by actually running
the Kite login — see auth.authenticate_with_totp). On success we mint a random
session token the browser stores and presents on subsequent requests, so the
TOTP is entered once per session, not per request.

In-memory and single-process: an API restart invalidates sessions (re-login).
Sessions expire after SESSION_TTL_HOURS (a trading day), matching the daily Kite
token lifecycle.
"""
import secrets
import threading
import time

SESSION_TTL_HOURS = 18


class SessionStore:
    def __init__(self, ttl_hours: float = SESSION_TTL_HOURS):
        self._ttl = ttl_hours * 3600
        self._tokens: dict[str, float] = {}   # token -> expiry epoch
        self._lock = threading.Lock()

    def create(self) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._tokens[token] = time.time() + self._ttl
        return token

    def validate(self, token: str) -> bool:
        if not token:
            return False
        with self._lock:
            exp = self._tokens.get(token)
            if exp is None:
                return False
            if exp < time.time():
                del self._tokens[token]
                return False
            return True

    def revoke(self, token: str) -> None:
        with self._lock:
            self._tokens.pop(token, None)

    def purge(self) -> None:
        now = time.time()
        with self._lock:
            for t in [t for t, e in self._tokens.items() if e < now]:
                del self._tokens[t]


_sessions = SessionStore()


def get_sessions() -> SessionStore:
    return _sessions
