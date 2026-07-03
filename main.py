"""
Trading Bot V1 — entry point.
Startup validation, trading cycle orchestration, EOD square-off, graceful shutdown.
"""
import os
import signal
import sys
import threading
import time
from datetime import datetime

import yaml
from dotenv import load_dotenv

from src.alert_manager import AlertManager
from src.auth import load_kite_session
from src.costs import estimate_intraday_costs, trade_leg_values
from src.data_fetcher import DataFetcher
from src.data_streamer import DataStreamer
from src.logger import get_logger, setup_logging
from src.market_calendar import MarketCalendar
from src.order_executor import OrderExecutor
from src.paper_trader import PaperTrader
from src.position_manager import PositionManager
from src.risk_manager import RiskManager
from src.state_store import StateStore
from src.strategy import generate_signal, market_regime
from src.telegram_controller import TelegramController
from src.trade_ledger import TradeLedger

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
    symbols = list(cfg["trading"]["watchlist"])
    if cfg["strategy"].get("regime_filter_enabled"):
        symbols.append(cfg["strategy"].get("regime_index_symbol", "NIFTY 50"))
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
        "ledger": TradeLedger(),
        "state": StateStore(),
        "calendar": MarketCalendar(cfg),
    }

    saved = ctx["state"].load()
    if saved:
        ctx["risk"].restore_counters(saved["daily_pnl"], saved["trades_today"])
        ctx["positions"].restore(saved["positions"])
        alert.send_raw(
            f"State restored after restart: {len(saved['positions'])} open positions, "
            f"P&L Rs.{saved['daily_pnl']:.2f}, {saved['trades_today']} trades today."
        )

    logger.info("All modules initialised — bot ready")
    return ctx


# ── Trading cycle ─────────────────────────────────────────────────────────────

def trading_cycle(ctx: dict, allow_entries: bool = True) -> None:
    """One complete 5-minute trading cycle (FR-22).
    allow_entries=False (Telegram /pause) manages positions but takes no new trades."""
    risk = ctx["risk"]
    triggered, reason = risk.check_circuit_breakers()
    if triggered:
        ctx["alert"].send("circuit_breaker", reason=reason)
        logger.warning(f"Circuit breaker active: {reason} — skipping cycle")
        return
    _manage_open_positions(ctx)
    if allow_entries:
        _scan_entries(ctx)
    else:
        logger.info("Paused — entry scan skipped")


def _reconcile_positions(ctx: dict) -> None:
    """Detect positions closed externally — GTT fired server-side or manual
    close in the Kite app (SCRUM-76). Removes them internally, records P&L
    from broker averages, and alerts. Prevents double exit orders.
    Skipped in paper mode (no real broker positions exist)."""
    if ctx["cfg"].get("paper_trading", {}).get("enabled", False):
        return
    positions = ctx["positions"]
    open_pos = positions.get_open_positions()
    if not open_pos:
        return

    try:
        day_book = ctx["kite"].positions().get("day", [])
        broker = {p["tradingsymbol"]: p for p in day_book}
    except Exception as exc:
        logger.warning(f"Reconciliation skipped — positions() failed: {exc}")
        return

    for pos in open_pos:
        bp = broker.get(pos.symbol)
        if bp is None:
            logger.warning(f"{pos.symbol}: open internally but absent from broker day book")
            continue
        expected = pos.quantity if pos.direction == "BUY" else -pos.quantity
        if bp["quantity"] == expected:
            continue
        if bp["quantity"] == 0:
            # closed at the broker — GTT fired or manual exit
            exit_price = bp["sell_price"] if pos.direction == "BUY" else bp["buy_price"]
            buy_v, sell_v = trade_leg_values(pos.direction, pos.entry_price,
                                             exit_price, pos.quantity)
            costs = estimate_intraday_costs(buy_v, sell_v, ctx["cfg"])
            pnl = pos.unrealized_pnl(exit_price) - costs
            positions.remove_position(pos.symbol)
            ctx["risk"].record_pnl(pnl)
            ctx["risk"].record_trade()
            ctx["ledger"].record(
                symbol=pos.symbol, direction=pos.direction, quantity=pos.quantity,
                entry_price=pos.entry_price, exit_price=exit_price,
                entry_time=pos.entry_time, exit_time=datetime.now(),
                pnl=pnl, exit_reason="external_exit",
            )
            ctx["alert"].send_raw(
                f"{pos.symbol} closed at broker (GTT fired or manual) @ {exit_price} | "
                f"P&L Rs.{pnl:.2f}"
            )
            logger.warning(f"{pos.symbol}: reconciled external exit @ {exit_price} | pnl={pnl:.2f}")
        else:
            logger.warning(
                f"{pos.symbol}: quantity mismatch — bot {expected}, broker {bp['quantity']}"
            )
            ctx["alert"].send_raw(
                f"WARNING: {pos.symbol} quantity mismatch — bot {expected}, "
                f"broker {bp['quantity']}. Check manually."
            )


def _manage_open_positions(ctx: dict) -> None:
    """Update trailing SL and exit positions that hit SL or target."""
    positions = ctx["positions"]
    _reconcile_positions(ctx)
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

    if not _within_entry_window(cfg):
        logger.info("Outside entry window — managing positions only")
        return

    watchlist = cfg["trading"]["watchlist"]
    open_symbols = {p.symbol for p in positions.get_open_positions()}
    candidates = [s for s in watchlist if s not in open_symbols]
    if not candidates:
        return

    quotes = _get_quotes(ctx, candidates)
    if quotes is None:
        logger.warning("Skipping entry scan — quote fetch failed")
        return

    regime = _get_regime(ctx)
    if regime == "NEUTRAL":
        logger.info("Market regime NEUTRAL — no entries this cycle")
        return

    margin = _get_margin(ctx)

    for symbol in candidates:
        if symbol not in quotes:
            continue
        if not _spread_ok(symbol, quotes[symbol], cfg):
            continue
        df = fetcher.get_candles(symbol)
        if df is None or df.empty:
            continue
        signal = generate_signal(symbol, df, cfg["strategy"])
        if signal.direction == "HOLD":
            continue
        if regime and ((signal.direction == "BUY" and regime != "BULLISH")
                       or (signal.direction == "SELL" and regime != "BEARISH")):
            logger.info(f"{symbol}: {signal.direction} signal against {regime} regime — skipped")
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


def _within_entry_window(cfg: dict) -> bool:
    """No new entries outside [entry_start_time, entry_end_time] (SCRUM-68).
    Window applies only when both keys are configured."""
    t = cfg["trading"]
    start, end = t.get("entry_start_time"), t.get("entry_end_time")
    if not start or not end:
        return True
    from datetime import time as dtime
    parse = lambda s: dtime(*map(int, s.split(":")))
    return parse(start) <= datetime.now().time() <= parse(end)


def _get_regime(ctx: dict):
    """NIFTY trend gate for entries (SCRUM-67).
    Returns BULLISH/BEARISH/NEUTRAL, or None when the filter is disabled or
    index data is unavailable (fail-open: filter off, entries allowed)."""
    cfg = ctx["cfg"]
    if not cfg["strategy"].get("regime_filter_enabled"):
        return None
    index_symbol = cfg["strategy"].get("regime_index_symbol", "NIFTY 50")
    df = ctx["fetcher"].get_candles(index_symbol)
    if df is None or df.empty:
        logger.warning("Regime filter: index candles unavailable — filter skipped")
        return None
    regime = market_regime(df, cfg["strategy"])
    logger.info(f"Market regime: {regime}")
    return regime


def _spread_ok(symbol: str, quote: dict, cfg: dict) -> bool:
    """Liquidity guard: block entry when the bid-ask spread is too wide (SCRUM-66).
    Quotes without depth data (e.g. from the WebSocket streamer) pass the check."""
    max_spread = cfg["risk"].get("max_spread_pct")
    if not max_spread:
        return True
    bid, ask, ltp = quote.get("bid"), quote.get("ask"), quote.get("ltp")
    if not bid or not ask or not ltp:
        return True
    spread_pct = (ask - bid) / ltp * 100
    if spread_pct > max_spread:
        logger.info(f"{symbol}: spread {spread_pct:.3f}% > {max_spread}% — entry skipped")
        return False
    return True


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

    buy_v, sell_v = trade_leg_values(removed.direction, removed.entry_price,
                                     exit_price, removed.quantity)
    costs = estimate_intraday_costs(buy_v, sell_v, ctx["cfg"])
    pnl = removed.unrealized_pnl(exit_price) - costs
    risk.record_pnl(pnl)
    risk.record_trade()
    risk.clear_api_errors()

    ctx["ledger"].record(
        symbol=removed.symbol, direction=removed.direction, quantity=removed.quantity,
        entry_price=removed.entry_price, exit_price=exit_price,
        entry_time=removed.entry_time, exit_time=datetime.now(),
        pnl=pnl, exit_reason=reason,
    )

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
    filled = (result or {}).get("filled_quantity", 0)

    if result is None or (result["status"] != "COMPLETE" and filled <= 0):
        # nothing filled — cancel any resting order and reject
        executor.cancel_order(order_id)
        reason = (result or {}).get("status_message", "timeout or unknown")
        alert.send("order_rejected", symbol=symbol, reason=reason)
        return

    if result["status"] != "COMPLETE":
        # partial fill on timeout — cancel the remainder, keep what we got (SCRUM-74)
        executor.cancel_order(order_id)
        logger.warning(f"{symbol}: partial fill {filled}/{qty} — remainder cancelled")
        alert.send("order_partial", symbol=symbol, filled=filled, requested=qty,
                   actual_price=result["average_price"])

    actual_qty = filled if filled > 0 else qty
    actual_price = result["average_price"]
    slippage = round(actual_price - signal.entry_price, 2)
    positions.add_position(symbol, signal.direction, actual_price,
                           actual_qty, signal.stop_loss, signal.target)
    risk.record_trade()
    risk.clear_api_errors()

    gtt_id = executor.place_gtt_oco(symbol, signal.direction, actual_qty,
                                     signal.stop_loss, signal.target, actual_price)
    if gtt_id:
        positions.set_gtt_id(symbol, gtt_id)

    alert.send("order_placed", direction=signal.direction, symbol=symbol,
               qty=actual_qty, price=actual_price, order_id=order_id)
    alert.send("order_filled", symbol=symbol, actual_price=actual_price, slippage=slippage)
    logger.info(f"Entry: {signal.direction} {actual_qty}x{symbol} @ {actual_price} | SL={signal.stop_loss}")


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
        buy_v, sell_v = trade_leg_values(pos.direction, pos.entry_price,
                                         exit_price, pos.quantity)
        costs = estimate_intraday_costs(buy_v, sell_v, ctx["cfg"])
        pnl = pos.unrealized_pnl(exit_price) - costs
        risk.record_pnl(pnl)
        positions.remove_position(pos.symbol)
        ctx["ledger"].record(
            symbol=pos.symbol, direction=pos.direction, quantity=pos.quantity,
            entry_price=pos.entry_price, exit_price=exit_price,
            entry_time=pos.entry_time, exit_time=datetime.now(),
            pnl=pnl, exit_reason="eod_square_off",
        )
        logger.info(f"EOD square-off: {pos.symbol} @ {exit_price} | P&L={pnl:.2f}")

    logger.info("All positions squared off")


def _save_state(ctx: dict) -> None:
    """Persist positions and daily counters for crash recovery (SCRUM-62)."""
    risk = ctx["risk"]
    ctx["state"].save(risk._daily_pnl, risk._trades_today,
                      ctx["positions"].get_open_positions())


def _maybe_heartbeat(ctx: dict, hb: dict) -> None:
    """Send an hourly 'alive' message so silence itself becomes an alert (SCRUM-64)."""
    interval = ctx["cfg"]["scheduler"].get("heartbeat_interval_minutes", 60) * 60
    now = time.monotonic()
    if now - hb["last"] < interval:
        return
    hb["last"] = now
    open_count = len(ctx["positions"].get_open_positions())
    streamer = ctx.get("streamer")
    stream_state = "connected" if (streamer and streamer.is_connected) else "disconnected"
    ctx["alert"].send_raw(
        f"Heartbeat: alive | {open_count} open positions | "
        f"streamer {stream_state} | P&L Rs.{ctx['risk']._daily_pnl:.2f}"
    )


def _send_daily_summary(ctx: dict) -> None:
    risk = ctx["risk"]
    ctx["alert"].send(
        "daily_summary",
        trades=risk._trades_today,
        profit=max(risk._daily_pnl, 0),
        loss=abs(min(risk._daily_pnl, 0)),
        net_pnl=risk._daily_pnl,
    )
    breakdown = ctx["ledger"].format_summary()
    if breakdown:
        ctx["alert"].send_raw(breakdown)


# ── Main loop ─────────────────────────────────────────────────────────────────

def run() -> int:
    """Bot entry point: startup, loop, graceful shutdown (FR-22, FR-24).
    Returns process exit code: 0 for clean shutdown, 1 on unhandled crash
    (the watchdog in start_bot.bat restarts only on non-zero)."""
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

    pause_event = threading.Event()

    def _status_message() -> str:
        open_pos = positions.get_open_positions()
        pos_lines = "\n".join(
            f"  {p.symbol} {p.direction} @ {p.entry_price:.2f} | SL={p.stop_loss:.2f} | Target={p.target:.2f}"
            for p in open_pos
        ) or "  None"
        return (
            f"Bot Status{' — PAUSED' if pause_event.is_set() else ''}\n"
            f"Market: {ctx['calendar'].status_text()}\n"
            f"Open positions ({len(open_pos)}):\n{pos_lines}\n"
            f"Daily P&L: Rs.{risk._daily_pnl:.2f}\n"
            f"Trades today: {risk._trades_today}"
        )

    controller = TelegramController(
        bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
        chat_id=os.getenv("TELEGRAM_CHAT_ID"),
        stop_event=stop_event,
        status_fn=_status_message,
        pause_event=pause_event,
    )
    controller.start()

    stop_reason = "normal shutdown"
    exit_code = 0
    hb = {"last": time.monotonic()}
    try:
        while not shutdown["requested"] and not stop_event.is_set():
            _maybe_heartbeat(ctx, hb)
            if not ctx["calendar"].is_trading_day():
                logger.info("Market holiday/weekend — idling")
                time.sleep(300)
                continue
            if not risk.is_market_open():
                if positions.is_square_off_time():
                    eod_square_off(ctx)
                    _send_daily_summary(ctx)
                    _save_state(ctx)
                    logger.info("EOD complete — waiting for next session")
                time.sleep(30)
                continue
            trading_cycle(ctx, allow_entries=not pause_event.is_set())
            _save_state(ctx)
            time.sleep(interval)
    except KeyboardInterrupt:
        stop_reason = "keyboard interrupt"
        logger.info("KeyboardInterrupt — initiating shutdown")
    except Exception as exc:
        stop_reason = f"unhandled exception: {exc}"
        exit_code = 1
        logger.critical(f"Unhandled exception in main loop: {exc}", exc_info=True)
        alert.send("critical_error", module="main", message=str(exc))
    finally:
        eod_square_off(ctx)
        _send_daily_summary(ctx)
        _save_state(ctx)
        alert.send("bot_stopped", reason=stop_reason)
        if "streamer" in ctx:
            ctx["streamer"].disconnect()
        controller.stop()
        logger.info("Bot shutdown complete")
    return exit_code


if __name__ == "__main__":
    sys.exit(run())
