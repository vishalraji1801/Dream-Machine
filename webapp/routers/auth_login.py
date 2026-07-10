"""
TOTP login (same flow as the bot's `bot auth`): the user enters their Kite TOTP,
the server runs the headless Kite login with server-side credentials, and on
success mints a browser session. Credentials (API key/secret, password) never
touch the browser.

Login is throttled — a 6-digit TOTP behind Tailscale is a second factor, and the
rate limit stops brute-forcing (and hammering Kite).
"""
import threading
import time

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from auth import AuthError, authenticate_with_totp
from src.logger import get_logger
from webapp.auth import _extract
from webapp.sessions import get_sessions

logger = get_logger("webapp.auth")
router = APIRouter(prefix="/api/auth")

_MAX_ATTEMPTS = 5
_WINDOW_SECONDS = 60
_attempts: list[float] = []
_lock = threading.Lock()


class LoginRequest(BaseModel):
    totp: str


def _throttled() -> bool:
    now = time.time()
    with _lock:
        _attempts[:] = [t for t in _attempts if now - t < _WINDOW_SECONDS]
        if len(_attempts) >= _MAX_ATTEMPTS:
            return True
        _attempts.append(now)
        return False


@router.post("/login")
def login(req: LoginRequest) -> dict:
    if _throttled():
        raise HTTPException(status_code=429,
                            detail="Too many attempts — wait a minute and try again.")
    try:
        result = authenticate_with_totp(req.totp)
    except AuthError as exc:
        logger.warning(f"TOTP login failed: {exc}")
        raise HTTPException(status_code=401, detail=str(exc))
    token = get_sessions().create()
    logger.warning(f"TOTP login succeeded for {result.get('user_id')}")
    return {"token": token, "user_id": result.get("user_id")}


@router.post("/logout")
def logout(authorization: str | None = Header(default=None),
           x_api_token: str | None = Header(default=None, alias="X-API-Token")) -> dict:
    token = _extract(authorization, x_api_token)
    if token:
        get_sessions().revoke(token)
    return {"ok": True}
