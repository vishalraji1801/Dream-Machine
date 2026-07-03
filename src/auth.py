"""
Token loader for bot startup.
Reads the saved access token and initialises a KiteConnect session.
"""
import os

from dotenv import load_dotenv
from kiteconnect import KiteConnect

from src.logger import get_logger

logger = get_logger("auth")

load_dotenv(dotenv_path=os.path.join("config", ".env"))


class AuthenticationError(Exception):
    pass


def load_kite_session() -> KiteConnect:
    """
    Read the access token saved by auth.py and return an authenticated KiteConnect instance.
    Raises AuthenticationError if the token file is missing, empty, or invalid.
    """
    api_key = os.getenv("KITE_API_KEY")
    token_path = os.getenv("KITE_ACCESS_TOKEN_PATH", "./token.txt")

    if not api_key:
        raise AuthenticationError("KITE_API_KEY missing from config/.env")

    if not os.path.exists(token_path):
        raise AuthenticationError(f"Token file not found: {token_path} — run auth.py first")

    with open(token_path) as f:
        access_token = f.read().strip()

    if not access_token:
        raise AuthenticationError(f"Token file is empty: {token_path} — run auth.py first")

    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(access_token)

    try:
        profile = kite.profile()
        logger.info(f"Kite session loaded for: {profile.get('user_name', 'unknown')} ({profile.get('user_id', '')})")
    except Exception as exc:
        raise AuthenticationError(f"Token validation failed — run auth.py to refresh: {exc}") from exc

    return kite
