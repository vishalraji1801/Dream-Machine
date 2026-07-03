"""
Trading Bot V1 — entry point.
Startup validation, trading cycle orchestration, EOD square-off, graceful shutdown.
"""
import os
import signal
import time

import yaml
from dotenv import load_dotenv

from src.alert_manager import AlertManager
from src.auth import load_kite_session
from src.data_fetcher import DataFetcher
from src.logger import get_logger, setup_logging
from src.order_executor import OrderExecutor
from src.position_manager import PositionManager
from src.risk_manager import RiskManager
from src.strategy import generate_signal

logger = get_logger("main")


# ── Startup ───────────────────────────────────────────────────────────────────

def load_config() -> dict:
    with open(os.path.join("config", "config.yaml")) as f:
        return yaml.safe_load(f)


def startup() -> dict:
    """
    Load config, initialise all modules, validate connections.
    Returns a context dict shared by all cycle functions (FR-23).
    Raises on any fatal startup failure.
    """
    load_dotenv(dotenv_path=os.path.join("config", ".env"))
    cfg = load_config()
    setup_logging(
        level=cfg["logging"]["level"],
        retention_days=cfg["logging"]["retention_days"],
    )
    logger.info("Trading Bot V1 starting up")

    kite = load_kite_session()

    alert = AlertManager(
        bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
        chat_id=os.getenv("TELEGRAM_CHAT_ID"),
    )

    fetcher = DataFetcher(kite, cfg)
    symbols = cfg["trading"]["watchlist"]
    if not fetcher.load_instruments(symbols):
        raise RuntimeError("Instrument load failed — cannot start without token map")

    ctx = {
        "cfg": cfg,
        "kite": kite,
        "alert": alert,
        "fetcher": fetcher,
        "executor": OrderExecutor(kite, cfg),
        "risk": RiskManager(cfg),
        "positions": PositionManager(cfg),
    }
    logger.info("All modules initialised — bot ready")
    return ctx


# ── Trading cycle ─────────────────────────────────────────────────────────────

def trading_cycle(ctx: dict) -> None:
    """One complete 5-minute trading cycle (FR-22)."""
    risk = ctx["risk"]
    triggered, reason = risk.check_circuit_breakers()
    if triggered:
        ctx["alert"].send("circuit_breaker", reason=reason)
        logger.warning(f"Circuit breaker active: {reason} — skipping cycle")
        return
    _manage_open_positions(ctx)
    _scan_entries(ctx)


def _manage_open_positions(ctx: dict) -> None:
    """Update trailing SL and exit positions that hit SL or target."""
    positions = ctx["positions"]
    fetcher = ctx["fetcher"]
    open_pos = positions.get_open_positions()
    if not open_pos:
        return

    symbols = [p.symbol for p in open_pos]
    quotes = fetcher.get_quotes(symbols)
    if quotes is None:
        logger.warning("Skipping position management — quote fetch failed")
        return

    for pos in open_pos:
        ltp = quotes.get(pos.symbol, {}).get("ltp")
        if ltp is None:
            continue
        positions.update_trailing_sl(pos.symbol, ltp)
        exiting, reason = positions.check_exit(pos.symbol, ltp)
        if exiting:
            _execute_exit(ctx, pos, ltp, reason)


def _scan_entries(ctx: dict) -> None:
    """Fetch data, generate signals, and place entry orders for open slots."""
    cfg = ctx["cfg"]
    risk = ctx["risk"]
    positions = ctx["positions"]
    fetcher = ctx["fetcher"]

    watchlist = cfg["trading"]["watchlist"]
    open_symbols = {p.symbol for p in positions.get_open_positions()}
    candidates = [s for s in watchlist if s not in open_symbols]
    if not candidates:
        return

    quotes = fetcher.get_quotes(candidates)
    if quotes is None:
        logger.warning("Skipping entry scan — quote fetch failed")
        return

    margin = _get_margin(ctx)

    for symbol in candidates:
        if symbol not in quotes:
            continue
        df = fetcher.get_candles(symbol)
        if df is None or df.empty:
            continue
        signal = generate_signal(symbol, df, cfg["strategy"])
        if signal.direction == "HOLD":
            continue
        qty = risk.calculate_quantity(signal.entry_price, signal.stop_loss)
        if qty <= 0:
            continue
        order_value = signal.entry_price * qty
        ok, block_reason = risk.check_pre_trade(order_value, margin, positions.open_count())
        if not ok:
            logger.info(f"Pre-trade blocked for {symbol}: {block_reason}")
            continue
        _execute_entry(ctx, symbol, signal, qty)
        break  # one entry per cycle to stay within position limits


def _get_margin(ctx: dict) -> float:
    """Fetch available equity margin from Kite. Returns 0.0 on error."""
    try:
        m = ctx["kite"].margins("equity")
        return float(m.get("available", {}).get("live_balance", 0.0))
    except Exception as exc:
        logger.warning(f"Could not fetch margin: {exc}")
        return 0.0


# ── Order helpers ─────────────────────────────────────────────────────────────

def _execute_exit(ctx: dict, pos, ltp: float, reason: str) -> None:
    """Place a market exit order and clean up the position."""
    executor = ctx["executor"]
    positions = ctx["positions"]
    risk = ctx["risk"]
    alert = ctx["alert"]

    exit_dir = "SELL" if pos.direction == "BUY" else "BUY"
    order_id = executor.place_order(pos.symbol, exit_dir, pos.quantity, ltp, "MARKET")
    if order_id is None:
        risk.record_api_error()
        return

    result = executor.monitor_order(order_id)
    exit_price = result["average_price"] if result else ltp
    removed = positions.remove_position(pos.symbol)
    if removed is None:
        return

    pnl = removed.unrealized_pnl(exit_price)
    risk.record_pnl(pnl)
    risk.record_trade()
    risk.clear_api_errors()

    if reason == "sl_hit":
        alert.send("sl_hit", symbol=pos.symbol, entry=pos.entry_price,
                   exit_price=exit_price, loss=abs(min(pnl, 0)))
    else:
        alert.send("target_hit", symbol=pos.symbol, entry=pos.entry_price,
                   exit_price=exit_price, profit=max(pnl, 0))

    logger.info(f"Exit: {pos.symbol} | reason={reason} | P&L={pnl:.2f}")


def _execute_entry(ctx: dict, symbol: str, signal, qty: int) -> None:
    """Place a limit entry order and open the position on fill."""
    executor = ctx["executor"]
    positions = ctx["positions"]
    risk = ctx["risk"]
    alert = ctx["alert"]
    cfg = ctx["cfg"]

    order_type = cfg["strategy"]["entry_order_type"]
    order_id = executor.place_order(symbol, signal.direction, qty,
                                    signal.entry_price, order_type)
    if order_id is None:
        risk.record_api_error()
        alert.send("order_rejected", symbol=symbol, reason="place_order returned None")
        return

    result = executor.monitor_order(order_id)
    if result is None or result["status"] != "COMPLETE":
        reason = (result or {}).get("status_message", "timeout or unknown")
        alert.send("order_rejected", symbol=symbol, reason=reason)
        return

    actual_price = result["average_price"]
    slippage = round(actual_price - signal.entry_price, 2)
    positions.add_position(symbol, signal.direction, actual_price,
                           qty, signal.stop_loss, signal.target)
    risk.record_trade()
    risk.clear_api_errors()

    alert.send("order_placed", direction=signal.direction, symbol=symbol,
               qty=qty, price=actual_price, order_id=order_id)
    alert.send("order_filled", symbol=symbol, actual_price=actual_price, slippage=slippage)
    logger.info(f"Entry: {signal.direction} {qty}x{symbol} @ {actual_price} | SL={signal.stop_loss}")


# ── EOD ───────────────────────────────────────────────────────────────────────

def eod_square_off(ctx: dict) -> None:
    """Market-order close all open positions at EOD (FR-24)."""
    positions = ctx["positions"]
    fetcher = ctx["fetcher"]
    executor = ctx["executor"]
    risk = ctx["risk"]

    to_close = positions.get_positions_for_square_off()
    if not to_close:
        return

    symbols = [p.symbol for p in to_close]
    quotes = fetcher.get_quotes(symbols) or {}

    for pos in to_close:
        ltp = quotes.get(pos.symbol, {}).get("ltp", pos.entry_price)
        exit_dir = "SELL" if pos.direction == "BUY" else "BUY"
        order_id = executor.place_order(pos.symbol, exit_dir, pos.quantity, ltp, "MARKET")
        if order_id:
            result = executor.monitor_order(order_id, timeout_sec=30)
            exit_price = result["average_price"] if result else ltp
        else:
            exit_price = ltp
        pnl = pos.unrealized_pnl(exit_price)
        risk.record_pnl(pnl)
        positions.remove_position(pos.symbol)
        logger.info(f"EOD square-off: {pos.symbol} @ {exit_price} | P&L={pnl:.2f}")

    logger.info("All positions squared off")


def _send_daily_summary(ctx: dict) -> None:
    risk = ctx["risk"]
    ctx["alert"].send(
        "daily_summary",
        trades=risk._trades_today,
        profit=max(risk._daily_pnl, 0),
        loss=abs(min(risk._daily_pnl, 0)),
        net_pnl=risk._daily_pnl,
    )


# ── Main loop ─────────────────────────────────────────────────────────────────

def run() -> None:
    """Bot entry point: startup, loop, graceful shutdown (FR-22, FR-24)."""
    ctx = startup()
    cfg = ctx["cfg"]
    risk = ctx["risk"]
    positions = ctx["positions"]
    interval = cfg["scheduler"]["cycle_interval_seconds"]

    ctx["alert"].send("bot_started", minutes=0)

    shutdown = {"requested": False}

    def _on_sigterm(*_):
        shutdown["requested"] = True
        logger.info("SIGTERM received — shutting down after this cycle")

    signal.signal(signal.SIGTERM, _on_sigterm)

    try:
        while not shutdown["requested"]:
            if not risk.is_market_open():
                if positions.is_square_off_time():
                    eod_square_off(ctx)
                    _send_daily_summary(ctx)
                    logger.info("EOD complete — waiting for next session")
                time.sleep(30)
                continue
            trading_cycle(ctx)
            time.sleep(interval)
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt — initiating shutdown")
    finally:
        eod_square_off(ctx)
        _send_daily_summary(ctx)
        logger.info("Bot shutdown complete")


if __name__ == "__main__":
    run()
