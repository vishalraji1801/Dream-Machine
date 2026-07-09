"""
Entry points:
  python -m webapp                 # run the server (0.0.0.0:8000)
  python -m webapp gen-token       # create/replace the API token
  python -m webapp --port 8080     # custom port
"""
import argparse
import sys


def _run() -> None:
    parser = argparse.ArgumentParser(prog="webapp")
    parser.add_argument("--host", default="0.0.0.0",
                        help="bind address (default 0.0.0.0 so Tailscale peers can reach it)")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="dev auto-reload")
    args = parser.parse_args()

    import uvicorn
    uvicorn.run("webapp.server:app", host=args.host, port=args.port,
                reload=args.reload)


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "gen-token":
        from webapp.settings import generate_token
        tok = generate_token()
        print("New API token written to config/webapp_token.txt:\n")
        print(f"    {tok}\n")
        print("Use it from the app, or as: Authorization: Bearer <token>")
        return
    _run()


if __name__ == "__main__":
    main()
