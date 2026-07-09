"""
Web app settings — single-user auth token and file paths.

The token is defence-in-depth on top of the Tailscale tunnel (the API is never
exposed publicly). Resolution order:
  1. env WEBAPP_TOKEN
  2. config/webapp_token.txt  (git-ignored; created by `python -m webapp gen-token`)
  3. None -> protected endpoints return 503 until a token is configured.
"""
import os
import secrets
from dataclasses import dataclass

_TOKEN_FILE = os.path.join("config", "webapp_token.txt")


def _load_token() -> str | None:
    env = os.getenv("WEBAPP_TOKEN")
    if env:
        return env.strip()
    if os.path.exists(_TOKEN_FILE):
        with open(_TOKEN_FILE, encoding="utf-8") as f:
            tok = f.read().strip()
            return tok or None
    return None


def generate_token() -> str:
    """Create and persist a new API token to config/webapp_token.txt."""
    tok = secrets.token_urlsafe(32)
    os.makedirs(os.path.dirname(_TOKEN_FILE) or ".", exist_ok=True)
    with open(_TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(tok + "\n")
    return tok


@dataclass(frozen=True)
class Settings:
    token: str | None
    config_path: str = os.path.join("config", "config.yaml")
    state_path: str = os.path.join("logs", "bot_state.json")
    log_dir: str = "logs"
    # CORS: the Vite dev server during frontend development. The built PWA is
    # served same-origin so needs no CORS entry.
    dev_origins: tuple = ("http://localhost:5173", "http://127.0.0.1:5173")


def get_settings() -> Settings:
    return Settings(token=_load_token())
