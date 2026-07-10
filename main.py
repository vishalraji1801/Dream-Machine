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

from src.ai_overlay import apply_overlay, load_overlay
from src.alert_manager import AlertManager
from src.auth import load_kite_session
from src.costs import estimate_intraday_costs, trade_leg_values
from src.data_fetcher import DataFetcher
from src.data_streamer import DataStreamer
from src.event_calendar import EventCalendar
from src.logger import get_logger, setup_logging
from src.market_calendar import MarketCalendar
from src.order_executor import OrderExecutor
from src.paper_trader import PaperTrader
from src.position_manager import PositionManager
from src.risk_manager import RiskManager
from src.scanner import rank as scanner_rank
from src.scanner import shadow_scan
from src.state_store import StateStore
from src.strategy import generate_signal, market_regime
from src.profile_store import ProfileStore
from src.tick_candle_builder import TickCandleBuilder
from src.universe_builder import UniverseBuilder
from src.volume_profile import RvolConfig, roll_profile, rvol as compute_rvol
from src.command_channel import CommandChannel
from src.telegram_controller import TelegramController
from src.trade_db import TradeDB
from src.trade_ledger import TradeLedger

logger = get_logger("main")


# ── Startup ───────────────────────────────────────────────────────────────────

def load_config() -> dict:
    with open(os.path.join("config", "config.yaml")) as f:
        return yaml.safe_load(f)


def _profile_suffix() -> str:
    """Isolate state/db files per BOT_PROFILE so parallel paper runs (e.g. 5min
    vs 1hr) don't collide. Empty when BOT_PROFILE is unset."""
    profile = os.getenv("BOT_PROFILE", "").strip()
    return f"_{profile}" if profile else ""


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

    paper_flag = cfg.get("paper_trading", {}).get("enabled", False)
    alert = AlertManager(
        bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
        chat_id=os.getenv("TELEGRAM_CHAT_ID"),
        tag="PAPER" if paper_flag else "LIVE",
    )

    # AI overlay (P5) — validated sandbox written by the scheduled Claude strategist.
    overlay, ov_err = load_overlay(cfg)
    if ov_err:
        logger.error(f"AI overlay REJECTED: {ov_err}")
        alert.send_raw(f"AI overlay REJECTED — running on config.yaml. Reason: {ov_err}")
    elif overlay:
        cfg = apply_overlay(cfg, overlay)
        logger.warning(f"AI overlay applied: {overlay}")
        alert.send_raw(f"AI overlay applied for today: {overlay}")

    fetcher = DataFetcher(kite, cfg)
    symbols = list(cfg["trading"]["watchlist"])

    # Dynamic universe (V2 P3) — opt-in. Loads today's pre-built universe file
    # and streams the whole set; falls back to the watchlist if absent.
    universe_symbols = None
    if cfg.get("universe", {}).get("enabled"):
        loaded = UniverseBuilder(cfg).load_today()
        if loaded:
            universe_symbols = [r["symbol"] for r in loaded]
            symbols = list(dict.fromkeys(universe_symbols + symbols))
            logger.info(f"Dynamic universe active: {len(universe_symbols)} symbols")
        else:
            logger.warning("universe.enabled but no universe file today — using watchlist. "
                           "Run build_universe.py pre-market.")

    if cfg["strategy"].get("regime_filter_enabled"):
        symbols.append(cfg["strategy"].get("regime_index_symbol", "NIFTY 50"))
    if not fetcher.load_instruments(symbols):
        raise RuntimeError("Instrument load failed — cannot start without token map")

    # Tick-built candles (SCRUM-106): seed closed bars once via REST, then the
    # WebSocket keeps them current — no per-cycle REST candle calls.
    feed = cfg.get("data_feed", {})
    candle_builder = None
    if feed.get("candles_from_ticks"):
        tf_seconds = {"minute": 60, "5minute": 300, "15minute": 900,
                      "30minute": 1800, "60minute": 3600}.get(cfg["trading"]["timeframe"], 900)
        candle_builder = TickCandleBuilder(interval_seconds=tf_seconds,
                                           max_bars=feed.get("max_bars", 120))
        if feed.get("seed_on_start", True):
            seeded = 0
            for sym in symbols:
                df = fetcher.get_candles(sym, lookback_days=feed.get("seed_lookback_days", 3))
                if df is not None and not df.empty:
                    if candle_builder.seed(sym, df, now_epoch=time.time()):
                        seeded += 1
            logger.info(f"Candle builder seeded from REST: {seeded}/{len(symbols)} symbols")

    streamer = DataStreamer(
        kite.api_key, kite.access_token, fetcher._instruments,
        max_tick_age_seconds=cfg["scheduler"].get("max_tick_age_seconds", 0),
        candle_builder=candle_builder,
    )
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
        "db": TradeDB(os.path.join("logs", f"trades{_profile_suffix()}.db")),
        "source": "paper" if paper_mode else "live",
        "state": StateStore(os.path.join("logs", f"bot_state{_profile_suffix()}.json")),
        "calendar": MarketCalendar(cfg),
        "events": EventCalendar(cfg),
        "universe_symbols": universe_symbols,
        "candles": candle_builder,
        "profiles": ProfileStore(),
        "rvol_cfg": RvolConfig(**cfg.get("universe", {}).get("rvol", {})),
    }

    saved = ctx["state"].load()
    if saved:
        ctx["risk"].restore_counters(saved["daily_pnl"], saved["trades_today"])
        ctx["positions"].restore(saved["positions"])
        alert.send_raw(
            f"State restored after restart: {len(saved['positions'])} open positions, "
            f"P&L Rs.{saved['daily_pnl']:.2f}, {saved['trades_today']} trades today."
        )

    _write_daily_universe(ctx)
    logger.info("All modules initialised — bot ready")
    return ctx


def _write_daily_universe(ctx: dict) -> None:
    """A0: snapshot today's traded membership (symbol -> token) so backtests can
    later replay the point-in-time list instead of today's survivors."""
    try:
        import csv
        os.makedirs("data_cache", exist_ok=True)
        path = os.path.join("data_cache", f"universe_{datetime.now():%Y-%m-%d}.csv")
        instruments = ctx["fetcher"]._instruments
        watchlist = ctx["cfg"]["trading"]["watchlist"]
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["symbol", "token"])
            for sym in watchlist:
                if sym in instruments:
                    w.writerow([sym, instruments[sym]])
        logger.info(f"Daily universe snapshot written: {path}")
    except Exception as exc:
        logger.warning(f"Could not write daily universe file: {exc}")


# ── Trading cycle ─────────────────────────────────────────────────────────────

def trading_cycle(ctx: dict, allow_entries: bool = True) -> None:
    """One complete 5-minute trading cycle (FR-22).
    allow_entries=False (Telegram /pause) manages positions but takes no new trades."""
    risk = ctx["risk"]
    ok, reason = risk.check_circuit_breakers()
    if not ok:
        ctx["alert"].send("circuit_breaker", reason=reason)
        logger.warning(f"Circuit breaker active: {reason} — skipping cycle")
        return
    _manage_open_positions(ctx)
    if allow_entries:
        _scan_entries(ctx)
    else:
        logger.info("Paused — entry scan skipped")

    _shadow_scan(ctx)

    db = ctx.get("db")
    if db is not None:
        db.record_snapshot(
            open_positions=ctx["positions"].open_count(),
            daily_pnl=risk._daily_pnl, trades_today=risk._trades_today,
        )


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
            _db_trade(ctx, pos, exit_price, pnl, costs, "external_exit")
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

    if not _within_entry_window(cfg):
        logger.info("Outside entry window — managing positions only")
        return

    events = ctx.get("events")
    if events and events.is_market_event_day():
        logger.info("Market event day — no entries today")
        return

    universe_on = cfg.get("universe", {}).get("enabled", False)
    base_symbols = (ctx.get("universe_symbols") or cfg["trading"]["watchlist"]) \
        if universe_on else cfg["trading"]["watchlist"]
    open_symbols = {p.symbol for p in positions.get_open_positions()}
    pool = [s for s in base_symbols if s not in open_symbols]
    if events:
        pool = [s for s in pool if not events.symbol_has_event(s)]
    if not pool:
        return

    quotes = _get_quotes(ctx, pool)
    if quotes is None:
        logger.warning("Skipping entry scan — quote fetch failed")
        return

    # Dynamic scanner (V2 P3): rank the pool, trade the top-N. Falls through to
    # the full pool when the universe is disabled.
    if universe_on:
        ranked = scanner_rank({s: {**quotes[s], "symbol": s} for s in quotes}, cfg)
        if ctx.get("db"):
            ctx["db"].record_scan(ranked)
        candidates = [r["symbol"] for r in ranked]
        logger.info(f"Scanner shortlist: {len(candidates)} of {len(pool)} names")
    else:
        candidates = pool

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
        df = _get_candles(ctx, symbol)
        if df is None or df.empty:
            continue
        signal = generate_signal(symbol, df, cfg["strategy"])
        if signal.direction == "HOLD":
            # persist MTF vetoes so their counterfactual value can be measured (B2)
            if signal.reason.startswith("mtf_veto") and signal.entry_price:
                vetoed_dir = signal.reason.split(":")[1]
                _db_signal(ctx, symbol, vetoed_dir, taken=False, reason=signal.reason)
                logger.info(f"{symbol}: MTF veto recorded ({signal.reason})")
            continue
        if regime and ((signal.direction == "BUY" and regime != "BULLISH")
                       or (signal.direction == "SELL" and regime != "BEARISH")):
            logger.info(f"{symbol}: {signal.direction} signal against {regime} regime — skipped")
            _db_signal(ctx, symbol, signal.direction, taken=False, reason="regime_mismatch")
            _alert_signal(ctx, symbol, signal, f"SKIPPED: against {regime} regime")
            continue
        qty = risk.calculate_quantity(signal.entry_price, signal.stop_loss)
        if qty <= 0:
            _db_signal(ctx, symbol, signal.direction, taken=False, reason="zero_quantity")
            _alert_signal(ctx, symbol, signal, "SKIPPED: zero quantity")
            continue
        order_value = signal.entry_price * qty
        ok, block_reason = risk.check_pre_trade(order_value, margin, positions.open_count())
        if not ok:
            logger.info(f"Pre-trade blocked for {symbol}: {block_reason}")
            _db_signal(ctx, symbol, signal.direction, taken=False, reason=block_reason)
            _alert_signal(ctx, symbol, signal, f"SKIPPED: {block_reason}")
            continue
        sector_ok, sector_reason = risk.check_sector_cap(symbol, list(open_symbols))
        if not sector_ok:
            logger.info(f"Sector cap blocked {symbol}: {sector_reason}")
            _db_signal(ctx, symbol, signal.direction, taken=False, reason=sector_reason)
            _alert_signal(ctx, symbol, signal, f"SKIPPED: {sector_reason}")
            continue
        _db_signal(ctx, symbol, signal.direction, taken=True)
        _alert_signal(ctx, symbol, signal, "ENTERING")
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
    df = _get_candles(ctx, index_symbol)
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


def _rvol_for(ctx: dict, symbol: str, quote: dict):
    """Time-of-day RVOL from the stored profile + today's cumulative volume (A1).
    None when no usable profile — the scanner then excludes it if require_rvol."""
    store = ctx.get("profiles")
    if store is None:
        return None
    try:
        profile = store.load(symbol)
        return compute_rvol(profile, float(quote.get("volume", 0.0) or 0.0),
                            datetime.now(), ctx["rvol_cfg"])
    except Exception:
        return None


def _roll_profiles(ctx: dict) -> None:
    """A1 deliverable 4: at EOD, roll each symbol's volume profile forward from
    today's tick-built candles (zero REST). Missing sessions are left for
    backfill_profiles.py; never rolls on partial/absent data."""
    builder = ctx.get("candles")
    store = ctx.get("profiles")
    if builder is None or store is None:
        return
    today = datetime.now().date()
    rolled = 0
    for sym in ctx["cfg"]["trading"]["watchlist"]:
        try:
            df = builder.get_candles(sym)
            profile = store.load(sym)
            if df is None or df.empty or profile is None:
                continue
            store.save(roll_profile(profile, today, df, ctx["rvol_cfg"]))
            rolled += 1
        except Exception as exc:
            logger.warning(f"profile roll failed for {sym}: {exc}")
    if rolled:
        logger.info(f"Rolled {rolled} volume profiles forward for {today}")


def _shadow_scan(ctx: dict) -> None:
    """A0: persist a full point-in-time scanner snapshot every cycle (rankings for
    ALL symbols + rejected-with-reason), so point-in-time universe history accrues
    now — even while we still trade the fixed watchlist. Trading is unaffected.
    Uses streamed quotes (no extra REST) and never raises into the cycle."""
    if not ctx["cfg"].get("scanner", {}).get("shadow_enabled", True):
        return
    db = ctx.get("db")
    if db is None:
        return
    try:
        watchlist = ctx["cfg"]["trading"]["watchlist"]
        quotes = _get_quotes(ctx, watchlist)
        if not quotes:
            return
        enriched = {s: {**quotes[s], "symbol": s, "rvol": _rvol_for(ctx, s, quotes[s])}
                    for s in quotes}
        ranked, rejected = shadow_scan(enriched, ctx["cfg"])
        db.record_scan(ranked, rejected=rejected)
    except Exception as exc:
        logger.warning(f"Shadow scan failed (non-fatal): {exc}")


def _get_candles(ctx: dict, symbol: str):
    """Candles for signal generation: tick-built once warm (zero REST calls),
    REST fallback while warming up or if the feed is disabled (SCRUM-106)."""
    builder = ctx.get("candles")
    if builder is not None:
        min_bars = ctx["cfg"].get("data_feed", {}).get("min_bars", 30)
        if builder.bar_count(symbol) >= min_bars:
            return builder.get_candles(symbol)
    return ctx["fetcher"].get_candles(symbol)


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
    """Available margin. PAPER mode simulates it from configured capital minus
    open exposure — the real account balance is irrelevant to a simulation
    (day-2 bug: real margin was Rs.0, so every paper entry was blocked)."""
    if ctx.get("source") == "paper":
        open_value = sum(p.entry_price * p.quantity
                         for p in ctx["positions"].get_open_positions())
        return max(0.0, float(ctx["cfg"]["risk"]["total_capital"]) - open_value)
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
    _db_trade(ctx, removed, exit_price, pnl, costs, reason)

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
               qty=actual_qty, price=actual_price, order_type=order_type,
               sl=signal.stop_loss, target=signal.target, order_id=order_id)
    alert.send("order_filled", symbol=symbol, actual_price=actual_price, slippage=slippage)
    logger.info(f"Entry: {signal.direction} {actual_qty}x{symbol} @ {actual_price} | SL={signal.stop_loss}")


# ── EOD ───────────────────────────────────────────────────────────────────────

def eod_square_off(ctx: dict) -> None:
    """Market-order close all open positions at EOD (FR-24)."""
    positions = ctx["positions"]
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
        _db_trade(ctx, pos, exit_price, pnl, costs, "eod_square_off")
        logger.info(f"EOD square-off: {pos.symbol} @ {exit_price} | P&L={pnl:.2f}")

    logger.info("All positions squared off")


def _save_state(ctx: dict) -> None:
    """Persist positions and daily counters for crash recovery (SCRUM-62)."""
    risk = ctx["risk"]
    ctx["state"].save(risk._daily_pnl, risk._trades_today,
                      ctx["positions"].get_open_positions())


def _db_trade(ctx: dict, pos, exit_price: float, pnl: float, costs: float, reason: str) -> None:
    """Record a closed trade to the SQLite ledger (V2 P1), tagged live/paper."""
    db = ctx.get("db")
    if db is None:
        return
    db.record_trade(
        source=ctx.get("source", "live"),
        strategy=ctx["cfg"]["strategy"].get("name"),
        symbol=pos.symbol, direction=pos.direction, quantity=pos.quantity,
        entry_price=pos.entry_price, exit_price=exit_price,
        entry_time=pos.entry_time, exit_time=datetime.now(),
        pnl=pnl, costs=costs, exit_reason=reason,
    )


def _db_signal(ctx: dict, symbol: str, direction: str, taken: bool, reason: str = "") -> None:
    db = ctx.get("db")
    if db is None:
        return
    db.record_signal(source=ctx.get("source", "live"), symbol=symbol,
                     direction=direction, taken=taken, reason=reason,
                     strategy=ctx["cfg"]["strategy"].get("name"))


def _alert_signal(ctx: dict, symbol: str, signal, action: str) -> None:
    """Signal alert with its OUTCOME, deduped per (symbol, direction, action)
    per day — a persisting-but-blocked signal must not spam every cycle."""
    log = ctx.setdefault("signal_alert_log", {"date": None, "sent": set()})
    today = datetime.now().date()
    if log["date"] != today:
        log["date"] = today
        log["sent"] = set()
    key = (symbol, signal.direction, action)
    if key in log["sent"]:
        return
    log["sent"].add(key)
    ctx["alert"].send("signal_generated", direction=signal.direction, symbol=symbol,
                      entry=signal.entry_price, sl=signal.stop_loss,
                      target=signal.target, action=action)


def _relay_ai_outbox(ctx: dict) -> None:
    """Send anything the scheduled Claude agents left in the Telegram outbox, then clear it."""
    path = ctx["cfg"].get("ai", {}).get("telegram_outbox")
    if not path or not os.path.exists(path):
        return
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read().strip()
        if text:
            ctx["alert"].send_raw(f"[AI] {text}")
        open(path, "w").close()  # truncate after relaying
    except OSError as exc:
        logger.warning(f"AI outbox relay failed: {exc}")


def _maybe_heartbeat(ctx: dict, hb: dict) -> None:
    """Send an hourly 'alive' message so silence itself becomes an alert (SCRUM-64)."""
    interval = ctx["cfg"]["scheduler"].get("heartbeat_interval_minutes", 60) * 60
    now = time.monotonic()
    if now - hb["last"] < interval:
        return
    hb["last"] = now
    open_pos = ctx["positions"].get_open_positions()
    streamer = ctx.get("streamer")
    stream_state = "connected" if (streamer and streamer.is_connected) else "disconnected"
    detail = ""
    if open_pos:
        quotes = _get_quotes(ctx, [p.symbol for p in open_pos]) or {}
        parts, unrealized = [], 0.0
        for p in open_pos:
            ltp = quotes.get(p.symbol, {}).get("ltp", p.entry_price)
            u = p.unrealized_pnl(ltp)
            unrealized += u
            parts.append(f"{p.direction} {p.quantity}x{p.symbol} @ {p.entry_price} ({u:+.0f})")
        detail = f"\nOpen: {'; '.join(parts)}\nUnrealized: Rs.{unrealized:+.2f}"
    ctx["alert"].send_raw(
        f"Heartbeat: alive | {len(open_pos)} open positions | "
        f"streamer {stream_state} | realized P&L Rs.{ctx['risk']._daily_pnl:.2f}{detail}"
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
    _roll_profiles(ctx)


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
        quotes = (_get_quotes(ctx, [p.symbol for p in open_pos]) or {}) if open_pos else {}
        lines, unrealized = [], 0.0
        for p in open_pos:
            ltp = quotes.get(p.symbol, {}).get("ltp", p.entry_price)
            u = p.unrealized_pnl(ltp)
            unrealized += u
            lines.append(f"  {p.direction} {p.quantity}x{p.symbol} @ {p.entry_price:.2f} | "
                         f"LTP {ltp:.2f} | SL {p.stop_loss:.2f} | Tgt {p.target:.2f} | {u:+.0f}")
        pos_block = "\n".join(lines) or "  None"
        return (
            f"Bot Status{' — PAUSED' if pause_event.is_set() else ''}\n"
            f"Market: {ctx['calendar'].status_text()}\n"
            f"Open positions ({len(open_pos)}):\n{pos_block}\n"
            f"Unrealized P&L: Rs.{unrealized:+.2f}\n"
            f"Realized P&L today: Rs.{risk._daily_pnl:+.2f}\n"
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

    # Out-of-process control channel for the web supervisor (mirrors Telegram
    # commands). Seek past any commands queued before this run started.
    commands = CommandChannel()
    commands.seek_to_end()

    def _process_commands() -> None:
        for entry in commands.poll():
            cmd = entry.get("cmd")
            if cmd == "stop":
                logger.warning("Command channel: stop — graceful shutdown")
                stop_event.set()
            elif cmd == "pause":
                pause_event.set()
                logger.warning("Command channel: pause — new entries suspended")
            elif cmd == "resume":
                pause_event.clear()
                logger.warning("Command channel: resume — entries re-enabled")
            elif cmd == "square_off":
                logger.warning("Command channel: square_off — flattening and pausing")
                eod_square_off(ctx)
                _save_state(ctx)
                pause_event.set()  # don't re-enter after a manual flatten

    stop_reason = "normal shutdown"
    exit_code = 0
    hb = {"last": time.monotonic()}
    eod_done = None  # date of the last completed EOD — square off/summary once per day
    try:
        while not shutdown["requested"] and not stop_event.is_set():
            _process_commands()
            if stop_event.is_set():
                break
            _maybe_heartbeat(ctx, hb)
            _relay_ai_outbox(ctx)
            if not ctx["calendar"].is_trading_day():
                logger.info("Market holiday/weekend — idling")
                time.sleep(300)
                continue
            if not risk.is_market_open():
                if positions.is_square_off_time() and eod_done != datetime.now().date():
                    eod_square_off(ctx)
                    _send_daily_summary(ctx)
                    _save_state(ctx)
                    eod_done = datetime.now().date()
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
