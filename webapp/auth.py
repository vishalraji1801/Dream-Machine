"""
Auth for the web app. The browser logs in with a TOTP (see routers/auth.py) and
receives a session token, presented as either:
  - Authorization: Bearer <token>
  - X-API-Token: <token>

A request is accepted if the token is a live session OR matches the optional
static WEBAPP_TOKEN (kept for scripts/automation and tests). Behind Tailscale
this is a second lock on top of network authentication.
"""
import hmac

from fastapi import Header, HTTPException, status

from webapp.sessions import get_sessions
from webapp.settings import get_settings


def token_is_valid(token: str | None) -> bool:
    if not token:
        return False
    if get_sessions().validate(token):
        return True
    static = get_settings().token
    return bool(static) and hmac.compare_digest(token, static)


def _extract(authorization: str | None, x_api_token: str | None) -> str | None:
    if x_api_token:
        return x_api_token.strip()
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


async def require_token(
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None, alias="X-API-Token"),
) -> None:
    provided = _extract(authorization, x_api_token)
    if not token_is_valid(provided):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated — log in with your TOTP",
        )
