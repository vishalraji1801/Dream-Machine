"""
Daily Kite login script.
Run once each morning before market open to generate and save the access token.
Usage: python auth.py
"""
import os
import sys
import webbrowser

from dotenv import load_dotenv
from kiteconnect import KiteConnect

load_dotenv(dotenv_path=os.path.join("config", ".env"))


def run_auth() -> None:
    api_key = os.getenv("KITE_API_KEY")
    api_secret = os.getenv("KITE_API_SECRET")
    token_path = os.getenv("KITE_ACCESS_TOKEN_PATH", "./token.txt")

    if not api_key or not api_secret:
        print("ERROR: KITE_API_KEY or KITE_API_SECRET missing from config/.env")
        sys.exit(1)

    kite = KiteConnect(api_key=api_key)
    login_url = kite.login_url()

    print(f"\nOpening Kite login in your browser...")
    print(f"URL: {login_url}\n")
    webbrowser.open(login_url)

    print("After logging in, copy the 'request_token' from the redirect URL.")
    print("It looks like: http://127.0.0.1?request_token=XXXX&action=login&status=success\n")
    request_token = input("Paste request_token here: ").strip()

    if not request_token:
        print("ERROR: No request_token provided.")
        sys.exit(1)

    session = kite.generate_session(request_token, api_secret=api_secret)
    access_token = session["access_token"]

    with open(token_path, "w") as f:
        f.write(access_token)

    print(f"\nToken saved to {token_path}")
    print("Bot is ready to start. Run: python main.py")


if __name__ == "__main__":
    run_auth()
