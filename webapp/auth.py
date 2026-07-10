"""
Single-user token auth. Accepts the token via either:
  - Authorization: Bearer <token>
  - X-API-Token: <token>

Behind Tailscale this is a second lock; it also stops a curious device on the
same tailnet from issuing control commands.
"""
import hmac

from fastapi import Header, HTTPException, status

from webapp.settings import get_settings


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
    settings = get_settings()
    if not settings.token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API token not configured. Run: python -m webapp gen-token",
        )
    provided = _extract(authorization, x_api_token)
    if not provided or not hmac.compare_digest(provided, settings.token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API token",
        )
