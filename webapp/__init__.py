"""
Web app backend (cross-device UI phase).

A FastAPI service that turns the headless bot into an application usable from a
phone and a laptop. It is the always-on host: it *reads* the state the bot
already persists (logs/trades.db, logs/bot_state.json) and, in later phases,
*supervises* the trading loop as a managed subprocess and pushes live updates
over WebSocket.

Design rule: the web stack never sits in the live order path. The API wraps the
existing modules (ops, trade_db, state_store, risk_manager, backtester,
strategy registry) — it does not reimplement bot logic.
"""
