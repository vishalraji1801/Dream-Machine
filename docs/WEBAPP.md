# Web app — cross-device UI

A responsive PWA (phone + laptop) over a FastAPI backend that supervises the bot.
The web stack never sits in the live order path: the API reads the state the bot
persists and controls it through a file-backed command channel.

```
  Phone / Laptop PWA ──(Tailscale)──> FastAPI (:8000) ──manages──> main.py (subprocess)
```

## Screens

- **Dashboard** — mode/running/market, daily & net P&L, positions, equity curve,
  signal feed, go-live gate checks, and controls (start / pause / resume /
  square-off / stop; LIVE start needs confirm)
- **Backtest** — run the Backtester over stored candles (background job), see
  aggregate + per-symbol results
- **Strategies** — view the registry, set the active strategy
- **Logs** — tail any `*.log` with auto-refresh
- **Settings** — edit risk / strategy / timing / scheduler params, validated,
  comments preserved; applies on the next bot start

## Layout

- `webapp/` — FastAPI backend
  - `server.py` app factory · `settings.py` token · `auth.py` token guard
  - `routers/monitor.py` reads · `routers/control.py` start/stop/pause/resume/squareoff
  - `supervisor.py` bot subprocess lifecycle · `ws.py` live WebSocket
  - `stores.py` read layer over TradeDB / StateStore / ops
  - `static/` built PWA (generated; git-ignored)
- `frontend/` — React + Vite + Tailwind PWA (source)

## First-time setup

```bash
# backend deps (into the venv)
.venv/Scripts/python -m pip install -r requirements.txt

# create the API token (writes config/webapp_token.txt, git-ignored)
.venv/Scripts/python -m webapp gen-token

# frontend deps + build (outputs to webapp/static)
cd frontend && npm install && npm run build
```

## Run (production, single origin)

```bash
.venv/Scripts/python -m webapp            # serves API + PWA on 0.0.0.0:8000
```

Or double-click `start_webapp.bat`. Open `http://localhost:8000`, paste the token
once (stored in the browser). On the phone, use the browser's "Add to Home Screen"
to install it as an app.

## Run (development, hot reload)

```bash
.venv/Scripts/python -m webapp --reload   # backend on :8000
cd frontend && npm run dev                # Vite on :5173, proxies /api and /ws
```

## Remote access from the phone (Tailscale)

1. Install Tailscale on the laptop and phone; sign into the same tailnet.
2. On the phone open `http://<laptop-tailscale-ip>:8000`.
3. Nothing is exposed publicly; the token is a second lock.

## Security

- Token via `Authorization: Bearer <t>` or `X-API-Token`; constant-time compare.
- `config/webapp_token.txt` and `webapp/static/` are git-ignored.
- Starting the bot in LIVE mode requires an explicit confirm (real orders never
  start on an accidental tap).
- Stop is graceful (bot squares off) via the command channel, not a hard kill.
