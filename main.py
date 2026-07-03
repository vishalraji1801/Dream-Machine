"""
Trading Bot V1 — entry point.
Startup validation, trading cycle orchestration, EOD square-off, graceful shutdown.
"""
import os
import signal
import threading
import time

import yaml
from dotenv import load_dotenv

from src.alert_manager import AlertManager
from src.auth import load_kite_session
from src.data_fetcher import DataFetcher
from src.data_streamer import DataStreamer
from src.logger import get_logger, setup_logging
from src.order_executor import OrderExecutor
from src.paper_trader import PaperTrader
from src.position_manager import PositionManager
from src.risk_manager import RiskManager
from src.strategy import generate_signal
from src.telegram_controller import TelegramController

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

    streamer = DataStreamer(kite.api_key, kite.access_token, fetcher._instruments)
    streamer.connect()

    paper_mode = cfg.get("paper_trading", {}).get("enabled", False)
    executor = PaperTrader(fetcher, cfg) if paper_mode else OrderExecutor(kite, cfg)
    if paper_mode:
        logger.warning("PAPER TRADING MODE — no real orders will be placed")
        alert.send_raw("PAPER TRADING MODE ACTIVE — simulating fills, no real orders.")

    ctx = {
        "cfg": cfg,
        "kite": kite,
        "alert": alert,
        "fetcher": fetcher,
        "streamer": streamer,
        "executor": executor,
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
    open_pos = positions.get_open_positions()
    if not open_pos:
        return

    symbols = [p.symbol for p in open_pos]
    quotes = _get_quotes(ctx, symbols)
    if quotes is None:
        logger.warning("Skipping position management — quote fetch failed")
        return

    for pos in open_pos:
        ltp = quotes.get(pos.symbol, {}).get("ltp")
        if ltp is None:
            continue
        new_sl = positions.update_trailing_sl(pos.symbol, ltp)
        if new_sl is not None and pos.gtt_id is not None:
            # Refresh GTT OCO with updated trailing SL
            ctx["executor"].cancel_gtt(pos.gtt_id)
            new_gtt = ctx["executor"].place_gtt_oco(
                pos.symbol, pos.direction, pos.quantity, new_sl, pos.target, ltp
            )
            if new_gtt:
                positions.set_gtt_id(pos.symbol, new_gtt)
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

    quotes = _get_quotes(ctx, candidates)
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
        ctx["alert"].send("signal_generated", direction=signal.direction, symbol=symbol,
                          entry=signal.entry_price, sl=signal.stop_loss, target=signal.target)
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


def _get_quotes(ctx: dict, symbols: list) -> dict | None:
    """Return quotes from KiteTicker if connected, else fall back to REST."""
    streamer = ctx.get("streamer")
    if streamer and streamer.is_connected:
        quotes = streamer.get_latest_quotes(symbols)
        if quotes:
            return quotes
        logger.info("Streamer connected but no ticks yet — falling back to REST")
    return ctx["fetcher"].get_quotes(symbols)


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

    if pos.gtt_id is not None:
        executor.cancel_gtt(pos.gtt_id)

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

    gtt_id = executor.place_gtt_oco(symbol, signal.direction, qty,
                                     signal.stop_loss, signal.target, actual_price)
    if gtt_id:
        positions.set_gtt_id(symbol, gtt_id)

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
    quotes = _get_quotes(ctx, symbols) or {}

    for pos in to_close:
        if pos.gtt_id is not None:
            executor.cancel_gtt(pos.gtt_id)
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
    alert = ctx["alert"]
    interval = cfg["scheduler"]["cycle_interval_seconds"]

    alert.send("bot_started", minutes=0)

    stop_event = threading.Event()
    shutdown = {"requested": False}

    def _on_sigterm(*_):
        shutdown["requested"] = True
        stop_event.set()
        logger.info("SIGTERM received — shutting down after this cycle")

    signal.signal(signal.SIGTERM, _on_sigterm)

    def _status_message() -> str:
        open_pos = positions.get_open_positions()
        pos_lines = "\n".join(
            f"  {p.symbol} {p.direction} @ {p.entry_price:.2f} | SL={p.stop_loss:.2f} | Target={p.target:.2f}"
            for p in open_pos
        ) or "  None"
        return (
            f"Bot Status\n"
            f"Open positions ({len(open_pos)}):\n{pos_lines}\n"
            f"Daily P&L: Rs.{risk._daily_pnl:.2f}\n"
            f"Trades today: {risk._trades_today}"
        )

    controller = TelegramController(
        bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
        chat_id=os.getenv("TELEGRAM_CHAT_ID"),
        stop_event=stop_event,
        status_fn=_status_message,
    )
    controller.start()

    stop_reason = "normal shutdown"
    try:
        while not shutdown["requested"] and not stop_event.is_set():
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
        stop_reason = "keyboard interrupt"
        logger.info("KeyboardInterrupt — initiating shutdown")
    except Exception as exc:
        stop_reason = f"unhandled exception: {exc}"
        logger.critical(f"Unhandled exception in main loop: {exc}", exc_info=True)
        alert.send("critical_error", module="main", message=str(exc))
    finally:
        eod_square_off(ctx)
        _send_daily_summary(ctx)
        alert.send("bot_stopped", reason=stop_reason)
        if "streamer" in ctx:
            ctx["streamer"].disconnect()
        controller.stop()
        logger.info("Bot shutdown complete")


if __name__ == "__main__":
    run()
