"""
Daily Kite login script — automated headless authentication.
Reads ZERODHA_USER_ID from config/.env; password comes from Windows
Credential Manager (keyring) with .env ZERODHA_PASSWORD as fallback.
Prompts for TOTP only, then saves the access token.

Usage:
    python auth.py                 # daily login (run via start_bot.bat)
    python auth.py --set-password  # store password securely, one time
"""
import os
import sys
from typing import Optional
from urllib.parse import parse_qs, urlparse

import requests as req
from dotenv import load_dotenv
from kiteconnect import KiteConnect

load_dotenv(dotenv_path=os.path.join("config", ".env"))

_KEYRING_SERVICE = "trading-bot"


def _get_password(user_id: str) -> Optional[str]:
    """Windows Credential Manager first, .env fallback."""
    try:
        import keyring
        pw = keyring.get_password(_KEYRING_SERVICE, user_id)
        if pw:
            return pw
    except Exception:
        pass
    return os.getenv("ZERODHA_PASSWORD")


def set_password() -> None:
    """Store the Zerodha password in Windows Credential Manager."""
    import getpass
    import keyring

    user_id = os.getenv("ZERODHA_USER_ID")
    if not user_id:
        print("ERROR: ZERODHA_USER_ID missing from config/.env")
        sys.exit(1)
    pw = getpass.getpass(f"Zerodha password for {user_id}: ")
    if not pw:
        print("ERROR: empty password.")
        sys.exit(1)
    keyring.set_password(_KEYRING_SERVICE, user_id, pw)
    print("Password stored in Windows Credential Manager.")
    print("You can now remove ZERODHA_PASSWORD from config/.env.")


def _market_closed_today() -> bool:
    """Weekend check — no trading on Saturday/Sunday."""
    from datetime import datetime
    return datetime.now().date().weekday() >= 5


def run_auth() -> str:
    """
    Authenticate with Kite Connect. Returns the access token.
    Saves it to KITE_ACCESS_TOKEN_PATH. Exits on failure.
    """
    if _market_closed_today() and "--force" not in sys.argv:
        print("Market is closed today (weekend) — not starting.")
        print("Use 'python auth.py --force' to authenticate anyway.")
        sys.exit(1)

    api_key    = os.getenv("KITE_API_KEY")
    api_secret = os.getenv("KITE_API_SECRET")
    user_id    = os.getenv("ZERODHA_USER_ID")
    token_path = os.getenv("KITE_ACCESS_TOKEN_PATH", "./token.txt")

    missing = [k for k, v in {
        "KITE_API_KEY": api_key, "KITE_API_SECRET": api_secret,
        "ZERODHA_USER_ID": user_id,
    }.items() if not v]
    if missing:
        print(f"ERROR: Missing from config/.env: {', '.join(missing)}")
        sys.exit(1)

    password = _get_password(user_id)
    if not password:
        print("ERROR: No password found. Run 'python auth.py --set-password' "
              "or set ZERODHA_PASSWORD in config/.env")
        sys.exit(1)

    totp = input("Enter TOTP: ").strip()
    if not totp:
        print("ERROR: TOTP is required.")
        sys.exit(1)

    print("Authenticating with Kite...")
    try:
        request_token = _headless_login(api_key, user_id, password, totp)
    except Exception as exc:
        print(f"ERROR: Authentication failed — {exc}")
        sys.exit(1)

    kite = KiteConnect(api_key=api_key)
    session_data = kite.generate_session(request_token, api_secret=api_secret)
    access_token = session_data["access_token"]

    with open(token_path, "w") as f:
        f.write(access_token)

    print(f"Authentication successful. Token saved to {token_path}")
    return access_token


def _headless_login(api_key: str, user_id: str, password: str, totp: str) -> str:
    """Automate Kite Connect OAuth via requests. Returns request_token."""
    s = req.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0"})

    # Step 1: Password login
    r = s.post(
        "https://kite.zerodha.com/api/login",
        data={"user_id": user_id, "password": password},
        timeout=15,
    )
    r.raise_for_status()
    body = r.json()
    if body.get("status") != "success":
        raise RuntimeError(f"Login failed: {body.get('message', body)}")
    request_id = body["data"]["request_id"]

    # Step 2: TOTP 2FA
    r = s.post(
        "https://kite.zerodha.com/api/twofa",
        data={
            "user_id": user_id,
            "request_id": request_id,
            "twofa_value": totp,
            "twofa_type": "totp",
        },
        timeout=15,
    )
    r.raise_for_status()
    body = r.json()
    if body.get("status") != "success":
        raise RuntimeError(f"2FA failed — wrong TOTP? ({body.get('message', body)})")

    # Step 3: OAuth redirect — capture request_token from callback URL
    connect_url = f"https://kite.zerodha.com/connect/login?v=3&api_key={api_key}"
    final_url = _capture_callback_url(s, connect_url)

    params = parse_qs(urlparse(final_url).query)
    token = params.get("request_token", [None])[0]
    if not token:
        raise RuntimeError(
            f"request_token not found in redirect URL: {final_url}\n"
            "Check that your Kite Connect app redirect URL is set in the developer console."
        )
    return token


def _capture_callback_url(session: req.Session, url: str) -> str:
    """
    Follow the Kite Connect OAuth redirect chain and return the callback URL
    that contains request_token. Handles both reachable and localhost callback URLs.
    """
    try:
        r = session.get(url, allow_redirects=True, timeout=15)
        if "request_token" in r.url:
            return r.url
        for resp in r.history:
            loc = resp.headers.get("Location", "")
            if "request_token" in loc:
                return loc
    except req.exceptions.ConnectionError as exc:
        # Redirect pointed to an unreachable host (e.g. http://127.0.0.1)
        # The failing request URL is the callback URL we need
        if exc.request and "request_token" in str(exc.request.url):
            return str(exc.request.url)
        # Fall through to raise below
    raise RuntimeError(
        "Could not capture the OAuth callback URL. "
        "Verify your Kite Connect app redirect URL is configured correctly."
    )


if __name__ == "__main__":
    if "--set-password" in sys.argv:
        set_password()
    else:
        run_auth()
