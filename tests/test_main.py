"""
Tests for main.py — startup, trading cycle, EOD square-off, graceful shutdown.
"""
from unittest.mock import MagicMock, patch, ANY
import pytest

import main
from src.position_manager import Position
from datetime import datetime


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_ctx(
    risk_halted=False,
    circuit_breaker=(True, ""),   # (ok, reason) — True means all clear
    open_positions=None,
    quotes=None,
    candles=None,
    signal_direction="HOLD",
    pre_trade_ok=True,
    margin=100000.0,
):
    cfg = {
        "trading": {"exchange": "NSE", "product_type": "MIS", "watchlist": ["RELIANCE", "TCS"],
                    "square_off_time": "15:15", "market_open": "09:15", "market_close": "15:30"},
        "strategy": {"entry_order_type": "LIMIT", "ema_fast": 9, "ema_slow": 21,
                     "rsi_period": 14, "rsi_entry_threshold": 60,
                     "volume_sma_period": 20, "volume_multiplier": 1.5,
                     "ema_crossover_lookback": 3},
        "risk": {"total_capital": 500000, "max_risk_per_trade_pct": 1.0,
                 "max_open_positions": 3, "max_position_size_pct": 20.0,
                 "order_value_cap": 120000, "stop_loss_pct": 1.0, "target_pct": 2.0,
                 "min_risk_reward": 2.0, "trailing_sl_enabled": True,
                 "trailing_sl_activation_pct": 1.0, "trailing_sl_step_pct": 0.5,
                 "max_daily_loss": 10000, "max_trades_per_day": 8,
                 "max_consecutive_api_errors": 3, "min_margin_threshold": 25000},
        "scheduler": {"cycle_interval_seconds": 300},
        "logging": {"level": "INFO", "retention_days": 30},
        "costs": {"enabled": False},  # cost subtraction tested explicitly
    }

    mock_signal = MagicMock()
    mock_signal.direction = signal_direction
    mock_signal.entry_price = 2850.0
    mock_signal.stop_loss = 2821.5
    mock_signal.target = 2907.0

    risk = MagicMock()
    risk.check_circuit_breakers.return_value = circuit_breaker
    risk.check_pre_trade.return_value = (pre_trade_ok, "ok" if pre_trade_ok else "blocked")
    risk.check_sector_cap.return_value = (True, "")
    risk.calculate_quantity.return_value = 10
    risk.is_market_open.return_value = True
    risk._daily_pnl = 500.0
    risk._trades_today = 3

    positions = MagicMock()
    positions.get_open_positions.return_value = open_positions or []
    positions.get_positions_for_square_off.return_value = open_positions or []
    positions.open_count.return_value = len(open_positions or [])
    positions.check_exit.return_value = (False, "")
    positions.is_square_off_time.return_value = False

    fetcher = MagicMock()
    fetcher.get_quotes.return_value = quotes
    fetcher.get_candles.return_value = candles

    executor = MagicMock()
    executor.place_order.return_value = "ORDER123"
    executor.monitor_order.return_value = {
        "status": "COMPLETE", "average_price": 2852.0,
        "filled_quantity": 10, "status_message": None
    }

    kite = MagicMock()
    kite.margins.return_value = {"available": {"live_balance": margin}}
    kite.positions.return_value = {"day": [], "net": []}

    alert = MagicMock()
    alert.send.return_value = True

    streamer = MagicMock()
    streamer.is_connected = False  # default: not connected → falls back to REST
    streamer.get_latest_quotes.return_value = quotes

    ledger = MagicMock()
    ledger.format_summary.return_value = None

    state = MagicMock()
    state.load.return_value = None

    calendar = MagicMock()
    calendar.is_trading_day.return_value = True
    calendar.is_market_open_now.return_value = True
    calendar.status_text.return_value = "OPEN"

    db = MagicMock()

    events = MagicMock()
    events.is_market_event_day.return_value = False
    events.symbol_has_event.return_value = False

    return {
        "cfg": cfg, "kite": kite, "alert": alert,
        "fetcher": fetcher, "streamer": streamer, "executor": executor,
        "risk": risk, "positions": positions, "ledger": ledger,
        "state": state, "calendar": calendar, "db": db, "source": "paper",
        "events": events,
        "_mock_signal": mock_signal,
    }


def _make_position(symbol="RELIANCE", direction="BUY", entry=2800.0, qty=10,
                   sl=2772.0, target=2856.0, gtt_id=None):
    pos = MagicMock(spec=Position)
    pos.symbol = symbol
    pos.direction = direction
    pos.entry_price = entry
    pos.quantity = qty
    pos.stop_loss = sl
    pos.target = target
    pos.gtt_id = gtt_id
    pos.entry_time = datetime(2026, 7, 3, 10, 15)
    pos.unrealized_pnl.return_value = 200.0
    return pos


# ── startup ───────────────────────────────────────────────────────────────────

def _patch_startup():
    return [
        patch("main.load_dotenv"),
        patch("main.load_config", return_value=_make_ctx()["cfg"]),
        patch("main.setup_logging"),
        patch("main.load_kite_session", return_value=MagicMock()),
        patch("main.AlertManager", return_value=MagicMock()),
        patch("main.DataStreamer", return_value=MagicMock()),
        patch("main.OrderExecutor", return_value=MagicMock()),
        patch("main.RiskManager", return_value=MagicMock()),
        patch("main.PositionManager", return_value=MagicMock()),
        patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "123"}),
    ]


def test_startup_returns_all_keys():
    with patch("main.load_dotenv"), \
         patch("main.load_config", return_value=_make_ctx()["cfg"]), \
         patch("main.setup_logging"), \
         patch("main.load_kite_session", return_value=MagicMock()), \
         patch("main.AlertManager", return_value=MagicMock()), \
         patch("main.DataFetcher") as MockFetcher, \
         patch("main.DataStreamer", return_value=MagicMock()), \
         patch("main.OrderExecutor", return_value=MagicMock()), \
         patch("main.RiskManager", return_value=MagicMock()), \
         patch("main.PositionManager", return_value=MagicMock()), \
         patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "123"}):
        mock_fetcher = MagicMock()
        mock_fetcher.load_instruments.return_value = True
        MockFetcher.return_value = mock_fetcher
        ctx = main.startup()

    for key in ("cfg", "kite", "alert", "fetcher", "streamer", "executor", "risk", "positions"):
        assert key in ctx


def test_startup_connects_streamer():
    with patch("main.load_dotenv"), \
         patch("main.load_config", return_value=_make_ctx()["cfg"]), \
         patch("main.setup_logging"), \
         patch("main.load_kite_session", return_value=MagicMock()), \
         patch("main.AlertManager", return_value=MagicMock()), \
         patch("main.DataFetcher") as MockFetcher, \
         patch("main.DataStreamer") as MockStreamer, \
         patch("main.OrderExecutor", return_value=MagicMock()), \
         patch("main.RiskManager", return_value=MagicMock()), \
         patch("main.PositionManager", return_value=MagicMock()), \
         patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "123"}):
        mock_fetcher = MagicMock()
        mock_fetcher.load_instruments.return_value = True
        MockFetcher.return_value = mock_fetcher
        mock_streamer = MagicMock()
        MockStreamer.return_value = mock_streamer
        main.startup()
    mock_streamer.connect.assert_called_once()


def test_startup_raises_if_instruments_fail():
    with patch("main.load_dotenv"), \
         patch("main.load_config", return_value=_make_ctx()["cfg"]), \
         patch("main.setup_logging"), \
         patch("main.load_kite_session", return_value=MagicMock()), \
         patch("main.AlertManager", return_value=MagicMock()), \
         patch("main.DataFetcher") as MockFetcher, \
         patch("main.DataStreamer", return_value=MagicMock()), \
         patch("main.OrderExecutor", return_value=MagicMock()), \
         patch("main.RiskManager", return_value=MagicMock()), \
         patch("main.PositionManager", return_value=MagicMock()), \
         patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "123"}):
        mock_fetcher = MagicMock()
        mock_fetcher.load_instruments.return_value = False
        MockFetcher.return_value = mock_fetcher
        with pytest.raises(RuntimeError, match="Instrument load failed"):
            main.startup()


def test_startup_uses_paper_trader_when_enabled():
    paper_cfg = {**_make_ctx()["cfg"], "paper_trading": {"enabled": True, "simulated_slippage_pct": 0.05}}
    with patch("main.load_dotenv"), \
         patch("main.load_config", return_value=paper_cfg), \
         patch("main.setup_logging"), \
         patch("main.load_kite_session", return_value=MagicMock()), \
         patch("main.AlertManager", return_value=MagicMock()), \
         patch("main.DataFetcher") as MockFetcher, \
         patch("main.DataStreamer", return_value=MagicMock()), \
         patch("main.PaperTrader") as MockPaper, \
         patch("main.OrderExecutor") as MockLive, \
         patch("main.RiskManager", return_value=MagicMock()), \
         patch("main.PositionManager", return_value=MagicMock()), \
         patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "123"}):
        mock_fetcher = MagicMock()
        mock_fetcher.load_instruments.return_value = True
        MockFetcher.return_value = mock_fetcher
        main.startup()
    MockPaper.assert_called_once()
    MockLive.assert_not_called()


def test_startup_uses_order_executor_when_paper_disabled():
    live_cfg = {**_make_ctx()["cfg"], "paper_trading": {"enabled": False}}
    with patch("main.load_dotenv"), \
         patch("main.load_config", return_value=live_cfg), \
         patch("main.setup_logging"), \
         patch("main.load_kite_session", return_value=MagicMock()), \
         patch("main.AlertManager", return_value=MagicMock()), \
         patch("main.DataFetcher") as MockFetcher, \
         patch("main.DataStreamer", return_value=MagicMock()), \
         patch("main.PaperTrader") as MockPaper, \
         patch("main.OrderExecutor") as MockLive, \
         patch("main.RiskManager", return_value=MagicMock()), \
         patch("main.PositionManager", return_value=MagicMock()), \
         patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "123"}):
        mock_fetcher = MagicMock()
        mock_fetcher.load_instruments.return_value = True
        MockFetcher.return_value = mock_fetcher
        main.startup()
    MockLive.assert_called_once()
    MockPaper.assert_not_called()


# ── trading_cycle ─────────────────────────────────────────────────────────────

def test_cycle_skips_on_circuit_breaker():
    ctx = _make_ctx(circuit_breaker=(False, "Daily loss limit hit"))  # ok=False -> tripped
    main.trading_cycle(ctx)
    ctx["alert"].send.assert_called_once_with("circuit_breaker", reason="Daily loss limit hit")
    ctx["fetcher"].get_quotes.assert_not_called()


def test_cycle_with_real_risk_manager_runs_when_clear():
    """Integration guard: mocks hid an inverted (ok, reason) contract once."""
    from src.risk_manager import RiskManager
    ctx = _make_ctx()
    ctx["risk"] = RiskManager(ctx["cfg"])          # real, freshly reset -> all clear
    with patch("main._manage_open_positions") as mock_manage, \
         patch("main._scan_entries") as mock_scan:
        main.trading_cycle(ctx)
    mock_manage.assert_called_once()
    mock_scan.assert_called_once()
    ctx["alert"].send.assert_not_called()          # no circuit_breaker alert


def test_cycle_with_real_risk_manager_halts_on_breach():
    from src.risk_manager import RiskManager
    ctx = _make_ctx()
    risk = RiskManager(ctx["cfg"])
    risk.record_pnl(-ctx["cfg"]["risk"]["max_daily_loss"] - 1)   # breach daily loss
    ctx["risk"] = risk
    with patch("main._manage_open_positions") as mock_manage, \
         patch("main._scan_entries") as mock_scan:
        main.trading_cycle(ctx)
    mock_manage.assert_not_called()
    mock_scan.assert_not_called()
    assert ctx["alert"].send.call_args.args[0] == "circuit_breaker"


def test_cycle_skips_entries_when_paused():
    ctx = _make_ctx()
    with patch("main._manage_open_positions") as mock_manage, \
         patch("main._scan_entries") as mock_scan:
        main.trading_cycle(ctx, allow_entries=False)
    mock_manage.assert_called_once()
    mock_scan.assert_not_called()


def test_cycle_calls_manage_positions_and_scan():
    ctx = _make_ctx(circuit_breaker=(True, ""))
    with patch("main._manage_open_positions") as mock_manage, \
         patch("main._scan_entries") as mock_scan:
        main.trading_cycle(ctx)
    mock_manage.assert_called_once_with(ctx)
    mock_scan.assert_called_once_with(ctx)


# ── _manage_open_positions ────────────────────────────────────────────────────

def test_manage_skips_when_no_open_positions():
    ctx = _make_ctx(open_positions=[])
    main._manage_open_positions(ctx)
    ctx["fetcher"].get_quotes.assert_not_called()


def test_manage_skips_when_quotes_fail():
    pos = _make_position()
    ctx = _make_ctx(open_positions=[pos], quotes=None)
    main._manage_open_positions(ctx)
    ctx["positions"].check_exit.assert_not_called()


def test_manage_updates_trailing_sl_and_checks_exit():
    pos = _make_position()
    ctx = _make_ctx(open_positions=[pos], quotes={"RELIANCE": {"ltp": 2870.0}})
    ctx["positions"].check_exit.return_value = (False, "")
    main._manage_open_positions(ctx)
    ctx["positions"].update_trailing_sl.assert_called_once_with("RELIANCE", 2870.0)
    ctx["positions"].check_exit.assert_called_once_with("RELIANCE", 2870.0)


def test_manage_executes_exit_when_sl_hit():
    pos = _make_position()
    ctx = _make_ctx(open_positions=[pos], quotes={"RELIANCE": {"ltp": 2770.0}})
    ctx["positions"].check_exit.return_value = (True, "sl_hit")
    ctx["positions"].remove_position.return_value = pos
    main._manage_open_positions(ctx)
    ctx["executor"].place_order.assert_called_once()
    ctx["alert"].send.assert_called()


# ── _scan_entries ─────────────────────────────────────────────────────────────

def test_scan_skips_if_all_symbols_in_positions():
    pos1 = _make_position("RELIANCE")
    pos2 = _make_position("TCS")
    ctx = _make_ctx(open_positions=[pos1, pos2])
    main._scan_entries(ctx)
    ctx["fetcher"].get_candles.assert_not_called()


def test_scan_skips_if_quotes_fail():
    ctx = _make_ctx(quotes=None)
    main._scan_entries(ctx)
    ctx["fetcher"].get_candles.assert_not_called()


def test_scan_skips_symbol_with_no_candles():
    ctx = _make_ctx(
        quotes={"RELIANCE": {"ltp": 2850.0}, "TCS": {"ltp": 3500.0}},
        candles=None,
    )
    with patch("main.generate_signal") as mock_sig:
        main._scan_entries(ctx)
    mock_sig.assert_not_called()


def test_scan_skips_hold_signal():
    import pandas as pd
    ctx = _make_ctx(
        quotes={"RELIANCE": {"ltp": 2850.0}, "TCS": {"ltp": 3500.0}},
        candles=pd.DataFrame({"timestamp": [], "open": [], "high": [], "low": [], "close": [], "volume": []}),
        signal_direction="HOLD",
    )
    with patch("main.generate_signal", return_value=ctx["_mock_signal"]):
        main._scan_entries(ctx)
    ctx["executor"].place_order.assert_not_called()


def test_scan_places_order_on_buy_signal():
    import pandas as pd
    ctx = _make_ctx(
        quotes={"RELIANCE": {"ltp": 2850.0}, "TCS": {"ltp": 3500.0}},
        candles=pd.DataFrame({"c": [1]}),
        signal_direction="BUY",
        pre_trade_ok=True,
    )
    ctx["_mock_signal"].direction = "BUY"
    with patch("main.generate_signal", return_value=ctx["_mock_signal"]):
        main._scan_entries(ctx)
    ctx["executor"].place_order.assert_called_once()


def test_scan_respects_pre_trade_block():
    import pandas as pd
    ctx = _make_ctx(
        quotes={"RELIANCE": {"ltp": 2850.0}, "TCS": {"ltp": 3500.0}},
        candles=pd.DataFrame({"c": [1]}),
        signal_direction="BUY",
        pre_trade_ok=False,
    )
    ctx["_mock_signal"].direction = "BUY"
    with patch("main.generate_signal", return_value=ctx["_mock_signal"]):
        main._scan_entries(ctx)
    ctx["executor"].place_order.assert_not_called()


# ── eod_square_off ────────────────────────────────────────────────────────────

def test_eod_square_off_no_positions():
    ctx = _make_ctx(open_positions=[])
    main.eod_square_off(ctx)
    ctx["executor"].place_order.assert_not_called()


def test_eod_square_off_places_market_sell_for_buy_position():
    pos = _make_position("RELIANCE", "BUY", entry=2800.0, qty=10)
    ctx = _make_ctx(open_positions=[pos], quotes={"RELIANCE": {"ltp": 2850.0}})
    main.eod_square_off(ctx)
    ctx["executor"].place_order.assert_called_once_with("RELIANCE", "SELL", 10, 2850.0, "MARKET")


def test_eod_square_off_places_market_buy_for_sell_position():
    pos = _make_position("TCS", "SELL", entry=3500.0, qty=5)
    ctx = _make_ctx(open_positions=[pos], quotes={"TCS": {"ltp": 3480.0}})
    main.eod_square_off(ctx)
    ctx["executor"].place_order.assert_called_once_with("TCS", "BUY", 5, 3480.0, "MARKET")


def test_eod_square_off_records_pnl():
    pos = _make_position("RELIANCE", "BUY")
    pos.unrealized_pnl.return_value = 500.0
    ctx = _make_ctx(open_positions=[pos], quotes={"RELIANCE": {"ltp": 2850.0}})
    main.eod_square_off(ctx)
    ctx["risk"].record_pnl.assert_called_once_with(500.0)


def test_eod_square_off_removes_position():
    pos = _make_position("RELIANCE", "BUY")
    ctx = _make_ctx(open_positions=[pos], quotes={"RELIANCE": {"ltp": 2850.0}})
    main.eod_square_off(ctx)
    ctx["positions"].remove_position.assert_called_once_with("RELIANCE")


# ── run / shutdown ────────────────────────────────────────────────────────────

def test_run_exits_cleanly_on_keyboard_interrupt():
    ctx = _make_ctx()
    ctx["risk"].is_market_open.return_value = False
    ctx["positions"].is_square_off_time.return_value = False

    with patch("main.startup", return_value=ctx), \
         patch("main.trading_cycle"), \
         patch("main.eod_square_off") as mock_eod, \
         patch("main._send_daily_summary") as mock_summary, \
         patch("main.TelegramController", return_value=MagicMock()), \
         patch("main.time.sleep", side_effect=KeyboardInterrupt):
        main.run()  # should not raise

    mock_eod.assert_called()
    mock_summary.assert_called()


def test_run_calls_eod_square_off_at_square_off_time():
    ctx = _make_ctx()
    ctx["risk"].is_market_open.return_value = False
    ctx["positions"].is_square_off_time.side_effect = [True, False, False]

    call_count = {"n": 0}
    def _sleep_then_stop(_):
        call_count["n"] += 1
        if call_count["n"] >= 3:
            raise KeyboardInterrupt

    with patch("main.startup", return_value=ctx), \
         patch("main.trading_cycle"), \
         patch("main.eod_square_off") as mock_eod, \
         patch("main._send_daily_summary"), \
         patch("main.TelegramController", return_value=MagicMock()), \
         patch("main.time.sleep", side_effect=_sleep_then_stop):
        main.run()

    assert mock_eod.call_count >= 1


def test_run_disconnects_streamer_on_shutdown():
    ctx = _make_ctx()
    ctx["risk"].is_market_open.return_value = False
    ctx["positions"].is_square_off_time.return_value = False

    with patch("main.startup", return_value=ctx), \
         patch("main.trading_cycle"), \
         patch("main.eod_square_off"), \
         patch("main._send_daily_summary"), \
         patch("main.TelegramController", return_value=MagicMock()), \
         patch("main.time.sleep", side_effect=KeyboardInterrupt):
        main.run()

    ctx["streamer"].disconnect.assert_called_once()


def test_run_sends_bot_stopped_alert_on_shutdown():
    ctx = _make_ctx()
    ctx["risk"].is_market_open.return_value = False
    ctx["positions"].is_square_off_time.return_value = False

    with patch("main.startup", return_value=ctx), \
         patch("main.trading_cycle"), \
         patch("main.eod_square_off"), \
         patch("main._send_daily_summary"), \
         patch("main.TelegramController", return_value=MagicMock()), \
         patch("main.time.sleep", side_effect=KeyboardInterrupt):
        main.run()

    ctx["alert"].send.assert_any_call("bot_stopped", reason="keyboard interrupt")


def test_run_sends_critical_error_on_unhandled_exception():
    ctx = _make_ctx()
    ctx["risk"].is_market_open.return_value = True

    with patch("main.startup", return_value=ctx), \
         patch("main.trading_cycle", side_effect=RuntimeError("boom")), \
         patch("main.eod_square_off"), \
         patch("main._send_daily_summary"), \
         patch("main.TelegramController", return_value=MagicMock()):
        main.run()

    ctx["alert"].send.assert_any_call("critical_error", module="main", message="boom")


def test_run_stop_event_exits_loop():
    """A /stop (pause_event unused here) sets stop_event before the first cycle;
    the loop must exit cleanly without ever calling trading_cycle."""
    ctx = _make_ctx()
    ctx["risk"].is_market_open.return_value = True
    call_count = {"n": 0}

    def _count_cycle(c, **kwargs):
        call_count["n"] += 1

    def fake_tc(bot_token, chat_id, stop_event, status_fn=None, pause_event=None):
        m = MagicMock()
        m.start = lambda: stop_event.set()  # simulate /stop arriving immediately
        return m

    with patch("main.startup", return_value=ctx), \
         patch("main.trading_cycle", side_effect=_count_cycle), \
         patch("main.eod_square_off"), \
         patch("main._send_daily_summary"), \
         patch("main.time.sleep"), \
         patch("main.TelegramController", side_effect=fake_tc):
        main.run()

    assert call_count["n"] == 0  # stop_event set before the first cycle


def test_run_eod_summary_sent_once_per_day():
    """After square-off time, the closed-market loop must not re-send the EOD
    report every 30s (day-1 paper bug: 8 duplicate Telegram summaries)."""
    ctx = _make_ctx()
    ctx["risk"].is_market_open.return_value = False
    ctx["positions"].is_square_off_time.return_value = True   # stays True after 15:15

    calls = {"n": 0}
    def _sleep(_):
        calls["n"] += 1
        if calls["n"] >= 4:                                   # 4 closed-market loops
            raise KeyboardInterrupt

    with patch("main.startup", return_value=ctx), \
         patch("main.trading_cycle"), \
         patch("main.eod_square_off"), \
         patch("main._send_daily_summary") as mock_summary, \
         patch("main.TelegramController", return_value=MagicMock()), \
         patch("main.time.sleep", side_effect=_sleep):
        main.run()

    # once in the loop + once in the shutdown finally — NOT once per iteration
    assert mock_summary.call_count == 2


# ── signal_generated alert ────────────────────────────────────────────────────

def test_scan_sends_signal_generated_alert_on_buy():
    import pandas as pd
    ctx = _make_ctx(
        quotes={"RELIANCE": {"ltp": 2850.0}, "TCS": {"ltp": 3500.0}},
        candles=pd.DataFrame({"c": [1]}),
        signal_direction="BUY",
        pre_trade_ok=True,
    )
    ctx["_mock_signal"].direction = "BUY"
    with patch("main.generate_signal", return_value=ctx["_mock_signal"]):
        main._scan_entries(ctx)
    ctx["alert"].send.assert_any_call(
        "signal_generated",
        direction="BUY",
        symbol="RELIANCE",
        entry=ctx["_mock_signal"].entry_price,
        sl=ctx["_mock_signal"].stop_loss,
        target=ctx["_mock_signal"].target,
    )


# ── KiteTicker / streamer integration ────────────────────────────────────────

def test_manage_uses_streamer_quotes_when_connected():
    pos = _make_position()
    ctx = _make_ctx(open_positions=[pos], quotes={"RELIANCE": {"ltp": 2870.0}})
    ctx["streamer"].is_connected = True
    ctx["streamer"].get_latest_quotes.return_value = {"RELIANCE": {"ltp": 2870.0}}
    ctx["positions"].check_exit.return_value = (False, "")
    main._manage_open_positions(ctx)
    ctx["streamer"].get_latest_quotes.assert_called_once_with(["RELIANCE"])
    ctx["fetcher"].get_quotes.assert_not_called()


def test_manage_falls_back_to_rest_when_streamer_disconnected():
    pos = _make_position()
    ctx = _make_ctx(open_positions=[pos], quotes={"RELIANCE": {"ltp": 2870.0}})
    ctx["streamer"].is_connected = False
    ctx["positions"].check_exit.return_value = (False, "")
    main._manage_open_positions(ctx)
    ctx["fetcher"].get_quotes.assert_called_once()


def test_manage_falls_back_to_rest_when_streamer_has_no_ticks():
    pos = _make_position()
    ctx = _make_ctx(open_positions=[pos], quotes={"RELIANCE": {"ltp": 2870.0}})
    ctx["streamer"].is_connected = True
    ctx["streamer"].get_latest_quotes.return_value = None  # no ticks buffered yet
    ctx["positions"].check_exit.return_value = (False, "")
    main._manage_open_positions(ctx)
    ctx["fetcher"].get_quotes.assert_called_once()


# ── GTT OCO integration ───────────────────────────────────────────────────────

def test_execute_entry_places_gtt_oco_after_fill():
    ctx = _make_ctx()
    ctx["executor"].place_gtt_oco.return_value = 777
    mock_signal = MagicMock()
    mock_signal.direction = "BUY"
    mock_signal.entry_price = 2850.0
    mock_signal.stop_loss = 2821.5
    mock_signal.target = 2907.0
    main._execute_entry(ctx, "RELIANCE", mock_signal, 10)
    ctx["executor"].place_gtt_oco.assert_called_once_with(
        "RELIANCE", "BUY", 10, 2821.5, 2907.0, 2852.0
    )
    ctx["positions"].set_gtt_id.assert_called_once_with("RELIANCE", 777)


def test_execute_exit_cancels_gtt_before_order():
    pos = _make_position(gtt_id=999)
    ctx = _make_ctx(open_positions=[pos])
    ctx["positions"].remove_position.return_value = pos
    main._execute_exit(ctx, pos, 2770.0, "sl_hit")
    ctx["executor"].cancel_gtt.assert_called_once_with(999)
    ctx["executor"].place_order.assert_called_once()


def test_execute_exit_no_gtt_cancel_when_no_gtt_id():
    pos = _make_position(gtt_id=None)
    ctx = _make_ctx(open_positions=[pos])
    ctx["positions"].remove_position.return_value = pos
    main._execute_exit(ctx, pos, 2770.0, "sl_hit")
    ctx["executor"].cancel_gtt.assert_not_called()


def test_eod_square_off_cancels_gtt_before_market_order():
    pos = _make_position("RELIANCE", "BUY", gtt_id=555)
    ctx = _make_ctx(open_positions=[pos], quotes={"RELIANCE": {"ltp": 2850.0}})
    main.eod_square_off(ctx)
    ctx["executor"].cancel_gtt.assert_called_once_with(555)
    ctx["executor"].place_order.assert_called_once()


def test_manage_refreshes_gtt_when_trailing_sl_updates():
    pos = _make_position(gtt_id=100)
    ctx = _make_ctx(open_positions=[pos], quotes={"RELIANCE": {"ltp": 2870.0}})
    ctx["streamer"].is_connected = False
    ctx["positions"].update_trailing_sl.return_value = 2814.0  # new SL
    ctx["positions"].check_exit.return_value = (False, "")
    ctx["executor"].place_gtt_oco.return_value = 101
    main._manage_open_positions(ctx)
    ctx["executor"].cancel_gtt.assert_called_once_with(100)
    ctx["executor"].place_gtt_oco.assert_called_once()
    ctx["positions"].set_gtt_id.assert_called_once_with("RELIANCE", 101)


# ── Trade ledger integration ──────────────────────────────────────────────────

def test_execute_exit_records_trade_in_ledger():
    pos = _make_position("RELIANCE", "BUY", entry=2800.0, qty=10)
    ctx = _make_ctx(open_positions=[pos])
    ctx["positions"].remove_position.return_value = pos
    main._execute_exit(ctx, pos, 2856.0, "target_hit")
    ctx["ledger"].record.assert_called_once()
    kwargs = ctx["ledger"].record.call_args.kwargs
    assert kwargs["symbol"] == "RELIANCE"
    assert kwargs["exit_reason"] == "target_hit"


def test_eod_square_off_records_trade_in_ledger():
    pos = _make_position("TCS", "SELL", entry=3500.0, qty=5)
    ctx = _make_ctx(open_positions=[pos], quotes={"TCS": {"ltp": 3480.0}})
    main.eod_square_off(ctx)
    ctx["ledger"].record.assert_called_once()
    assert ctx["ledger"].record.call_args.kwargs["exit_reason"] == "eod_square_off"


def test_daily_summary_sends_trade_breakdown_when_trades_exist():
    ctx = _make_ctx()
    ctx["ledger"].format_summary.return_value = "Today's trades:\nBUY 10xRELIANCE | +560.00"
    main._send_daily_summary(ctx)
    ctx["alert"].send_raw.assert_called_once_with(
        "Today's trades:\nBUY 10xRELIANCE | +560.00"
    )


def test_daily_summary_skips_breakdown_when_no_trades():
    ctx = _make_ctx()
    ctx["ledger"].format_summary.return_value = None
    main._send_daily_summary(ctx)
    ctx["alert"].send_raw.assert_not_called()


# ── Partial fills (SCRUM-74) ──────────────────────────────────────────────────

def _entry_signal():
    s = MagicMock()
    s.direction = "BUY"
    s.entry_price = 2850.0
    s.stop_loss = 2821.5
    s.target = 2907.0
    return s


def test_partial_fill_opens_position_with_filled_qty():
    ctx = _make_ctx()
    ctx["executor"].monitor_order.return_value = {
        "status": "OPEN", "average_price": 2851.0,
        "filled_quantity": 4, "pending_quantity": 6, "status_message": None,
    }
    main._execute_entry(ctx, "RELIANCE", _entry_signal(), 10)
    ctx["executor"].cancel_order.assert_called_once()  # remainder cancelled
    args = ctx["positions"].add_position.call_args.args
    assert args[3] == 4  # quantity = filled, not requested
    gtt_args = ctx["executor"].place_gtt_oco.call_args.args
    assert gtt_args[2] == 4  # GTT sized to actual position
    ctx["alert"].send.assert_any_call("order_partial", symbol="RELIANCE",
                                      filled=4, requested=10, actual_price=2851.0)


def test_zero_fill_timeout_cancels_and_rejects():
    ctx = _make_ctx()
    ctx["executor"].monitor_order.return_value = {
        "status": "OPEN", "average_price": 0.0,
        "filled_quantity": 0, "pending_quantity": 10, "status_message": "timeout",
    }
    main._execute_entry(ctx, "RELIANCE", _entry_signal(), 10)
    ctx["executor"].cancel_order.assert_called_once()
    ctx["positions"].add_position.assert_not_called()
    ctx["alert"].send.assert_any_call("order_rejected", symbol="RELIANCE", reason="timeout")


def test_complete_fill_uses_filled_quantity():
    ctx = _make_ctx()
    ctx["executor"].monitor_order.return_value = {
        "status": "COMPLETE", "average_price": 2852.0,
        "filled_quantity": 10, "pending_quantity": 0, "status_message": None,
    }
    main._execute_entry(ctx, "RELIANCE", _entry_signal(), 10)
    ctx["executor"].cancel_order.assert_not_called()
    assert ctx["positions"].add_position.call_args.args[3] == 10


# ── Broker reconciliation (SCRUM-76) ──────────────────────────────────────────

def test_reconcile_skipped_in_paper_mode():
    pos = _make_position()
    ctx = _make_ctx(open_positions=[pos])
    ctx["cfg"]["paper_trading"] = {"enabled": True}
    main._reconcile_positions(ctx)
    ctx["kite"].positions.assert_not_called()


def test_reconcile_removes_externally_closed_position():
    pos = _make_position("RELIANCE", "BUY", entry=2800.0, qty=10)
    pos.unrealized_pnl.return_value = 560.0
    ctx = _make_ctx(open_positions=[pos])
    ctx["kite"].positions.return_value = {"day": [{
        "tradingsymbol": "RELIANCE", "quantity": 0,
        "buy_price": 2800.0, "sell_price": 2856.0,
    }]}
    main._reconcile_positions(ctx)
    ctx["positions"].remove_position.assert_called_once_with("RELIANCE")
    ctx["risk"].record_pnl.assert_called_once()
    ctx["ledger"].record.assert_called_once()
    assert ctx["ledger"].record.call_args.kwargs["exit_reason"] == "external_exit"
    ctx["alert"].send_raw.assert_called_once()


def test_reconcile_leaves_matching_position_alone():
    pos = _make_position("RELIANCE", "BUY", qty=10)
    ctx = _make_ctx(open_positions=[pos])
    ctx["kite"].positions.return_value = {"day": [{
        "tradingsymbol": "RELIANCE", "quantity": 10,
        "buy_price": 2800.0, "sell_price": 0.0,
    }]}
    main._reconcile_positions(ctx)
    ctx["positions"].remove_position.assert_not_called()


def test_reconcile_warns_on_quantity_mismatch():
    pos = _make_position("RELIANCE", "BUY", qty=10)
    ctx = _make_ctx(open_positions=[pos])
    ctx["kite"].positions.return_value = {"day": [{
        "tradingsymbol": "RELIANCE", "quantity": 4,
        "buy_price": 2800.0, "sell_price": 2856.0,
    }]}
    main._reconcile_positions(ctx)
    ctx["positions"].remove_position.assert_not_called()
    assert "mismatch" in ctx["alert"].send_raw.call_args.args[0].lower()


def test_reconcile_survives_api_failure():
    pos = _make_position()
    ctx = _make_ctx(open_positions=[pos])
    ctx["kite"].positions.side_effect = Exception("API down")
    main._reconcile_positions(ctx)  # should not raise
    ctx["positions"].remove_position.assert_not_called()


def test_reconcile_sell_position_closed_externally():
    pos = _make_position("TCS", "SELL", entry=3500.0, qty=5)
    pos.unrealized_pnl.return_value = 250.0
    ctx = _make_ctx(open_positions=[pos])
    ctx["kite"].positions.return_value = {"day": [{
        "tradingsymbol": "TCS", "quantity": 0,
        "buy_price": 3450.0, "sell_price": 3500.0,
    }]}
    main._reconcile_positions(ctx)
    ctx["positions"].remove_position.assert_called_once_with("TCS")
    # exit price for a SELL is the broker buy average
    assert ctx["ledger"].record.call_args.kwargs["exit_price"] == 3450.0


# ── Market calendar in run loop (SCRUM-73) ────────────────────────────────────

def test_run_idles_on_holiday():
    ctx = _make_ctx()
    ctx["calendar"].is_trading_day.return_value = False
    with patch("main.startup", return_value=ctx), \
         patch("main.trading_cycle") as mock_cycle, \
         patch("main.eod_square_off"), \
         patch("main._send_daily_summary"), \
         patch("main.TelegramController", return_value=MagicMock()), \
         patch("main.time.sleep", side_effect=KeyboardInterrupt):
        main.run()
    mock_cycle.assert_not_called()
    ctx["risk"].is_market_open.assert_not_called()  # calendar short-circuits


# ── V2 P3: dynamic universe scanner hook ──────────────────────────────────────

def test_scan_uses_scanner_shortlist_when_universe_enabled():
    import pandas as pd
    ctx = _make_ctx(
        quotes={"AAA": {"ltp": 108.0, "close": 100.0, "high": 109.0, "low": 99.0, "open": 100.0},
                "BBB": {"ltp": 101.0, "close": 100.0, "high": 102.0, "low": 99.0, "open": 100.0}},
        candles=pd.DataFrame({"c": [1]}),
        signal_direction="HOLD",
    )
    ctx["cfg"]["universe"] = {"enabled": True}
    ctx["cfg"]["scanner"] = {"top_n": 1, "w_pct_change": 1.0, "w_range_pos": 2.0, "w_gap": 0.5}
    ctx["universe_symbols"] = ["AAA", "BBB"]
    with patch("main._get_regime", return_value="BULLISH"), \
         patch("main.generate_signal", return_value=ctx["_mock_signal"]) as mock_gen:
        main._scan_entries(ctx)
    ctx["db"].record_scan.assert_called_once()
    # only the top-ranked symbol (AAA, the bigger mover) is evaluated
    called = [c.args[0] for c in mock_gen.call_args_list]
    assert called == ["AAA"]


def test_scan_uses_watchlist_when_universe_disabled():
    import pandas as pd
    ctx = _make_ctx(
        quotes={"RELIANCE": {"ltp": 2850.0}, "TCS": {"ltp": 3500.0}},
        candles=pd.DataFrame({"c": [1]}),
        signal_direction="HOLD",
    )
    # no universe section -> disabled
    with patch("main._get_regime", return_value="BULLISH"), \
         patch("main.generate_signal", return_value=ctx["_mock_signal"]):
        main._scan_entries(ctx)
    ctx["db"].record_scan.assert_not_called()


# ── V2 P6: event calendar & sector cap ────────────────────────────────────────

def test_scan_skips_all_on_market_event_day():
    ctx = _make_ctx(quotes={"RELIANCE": {"ltp": 2850.0}})
    ctx["events"].is_market_event_day.return_value = True
    main._scan_entries(ctx)
    ctx["fetcher"].get_quotes.assert_not_called()


def test_scan_drops_symbol_with_earnings_event():
    import pandas as pd
    ctx = _make_ctx(
        quotes={"TCS": {"ltp": 3500.0}},
        candles=pd.DataFrame({"c": [1]}),
        signal_direction="BUY",
    )
    ctx["events"].symbol_has_event.side_effect = lambda s: s == "RELIANCE"
    ctx["_mock_signal"].direction = "BUY"
    with patch("main._get_regime", return_value="BULLISH"), \
         patch("main.generate_signal", return_value=ctx["_mock_signal"]) as mock_gen:
        main._scan_entries(ctx)
    called = [c.args[0] for c in mock_gen.call_args_list]
    assert "RELIANCE" not in called  # dropped by earnings event
    assert "TCS" in called


def test_scan_respects_sector_cap():
    import pandas as pd
    ctx = _make_ctx(
        quotes={"RELIANCE": {"ltp": 2850.0}, "TCS": {"ltp": 3500.0}},
        candles=pd.DataFrame({"c": [1]}),
        signal_direction="BUY",
    )
    ctx["risk"].check_sector_cap.return_value = (False, "sector cap for ENERGY reached (2)")
    ctx["_mock_signal"].direction = "BUY"
    with patch("main._get_regime", return_value="BULLISH"), \
         patch("main.generate_signal", return_value=ctx["_mock_signal"]):
        main._scan_entries(ctx)
    ctx["executor"].place_order.assert_not_called()


# ── V2 P1: SQLite ledger recording ────────────────────────────────────────────

def test_execute_exit_records_trade_to_db():
    pos = _make_position("RELIANCE", "BUY", entry=2800.0, qty=10)
    ctx = _make_ctx(open_positions=[pos])
    ctx["positions"].remove_position.return_value = pos
    main._execute_exit(ctx, pos, 2856.0, "target_hit")
    ctx["db"].record_trade.assert_called_once()
    kwargs = ctx["db"].record_trade.call_args.kwargs
    assert kwargs["source"] == "paper"
    assert kwargs["symbol"] == "RELIANCE"
    assert kwargs["exit_reason"] == "target_hit"


def test_scan_records_skipped_signal_on_regime_block():
    import pandas as pd
    ctx = _make_ctx(
        quotes={"RELIANCE": {"ltp": 2850.0}, "TCS": {"ltp": 3500.0}},
        candles=pd.DataFrame({"c": [1]}),
        signal_direction="BUY",
    )
    ctx["_mock_signal"].direction = "BUY"
    with patch("main._get_regime", return_value="BEARISH"), \
         patch("main.generate_signal", return_value=ctx["_mock_signal"]):
        main._scan_entries(ctx)
    ctx["db"].record_signal.assert_any_call(
        source="paper", symbol="RELIANCE", direction="BUY",
        taken=False, reason="regime_mismatch", strategy=ANY)


def test_trading_cycle_records_snapshot():
    ctx = _make_ctx()
    with patch("main._manage_open_positions"), patch("main._scan_entries"):
        main.trading_cycle(ctx)
    ctx["db"].record_snapshot.assert_called_once()


# ── V2 P2: AI Telegram outbox relay ───────────────────────────────────────────

def test_relay_ai_outbox_sends_and_clears(tmp_path):
    outbox = tmp_path / "telegram_outbox.txt"
    outbox.write_text("Post-market: 3 trades, net +Rs.420, PF 1.4")
    ctx = _make_ctx()
    ctx["cfg"]["ai"] = {"telegram_outbox": str(outbox)}
    main._relay_ai_outbox(ctx)
    ctx["alert"].send_raw.assert_called_once()
    assert "Post-market" in ctx["alert"].send_raw.call_args.args[0]
    assert outbox.read_text() == ""  # cleared after relay


def test_relay_ai_outbox_noop_when_empty(tmp_path):
    outbox = tmp_path / "telegram_outbox.txt"
    outbox.write_text("   \n")
    ctx = _make_ctx()
    ctx["cfg"]["ai"] = {"telegram_outbox": str(outbox)}
    main._relay_ai_outbox(ctx)
    ctx["alert"].send_raw.assert_not_called()


def test_relay_ai_outbox_noop_when_no_file(tmp_path):
    ctx = _make_ctx()
    ctx["cfg"]["ai"] = {"telegram_outbox": str(tmp_path / "missing.txt")}
    main._relay_ai_outbox(ctx)  # should not raise
    ctx["alert"].send_raw.assert_not_called()


# ── Transaction costs (SCRUM-65) ──────────────────────────────────────────────

def test_execute_exit_subtracts_costs_when_enabled():
    pos = _make_position("RELIANCE", "BUY", entry=2800.0, qty=10)
    pos.unrealized_pnl.return_value = 500.0
    ctx = _make_ctx(open_positions=[pos])
    ctx["cfg"]["costs"] = {"enabled": True}
    ctx["positions"].remove_position.return_value = pos
    main._execute_exit(ctx, pos, 2850.0, "target_hit")
    recorded = ctx["risk"].record_pnl.call_args.args[0]
    assert recorded < 500.0          # costs subtracted
    assert recorded > 450.0          # but only by a realistic amount


def test_execute_exit_gross_pnl_when_costs_disabled():
    pos = _make_position("RELIANCE", "BUY", entry=2800.0, qty=10)
    pos.unrealized_pnl.return_value = 500.0
    ctx = _make_ctx(open_positions=[pos])
    ctx["positions"].remove_position.return_value = pos
    main._execute_exit(ctx, pos, 2850.0, "target_hit")
    assert ctx["risk"].record_pnl.call_args.args[0] == 500.0


def test_eod_square_off_subtracts_costs_when_enabled():
    pos = _make_position("RELIANCE", "BUY", entry=2800.0, qty=10)
    pos.unrealized_pnl.return_value = 500.0
    ctx = _make_ctx(open_positions=[pos], quotes={"RELIANCE": {"ltp": 2850.0}})
    ctx["cfg"]["costs"] = {"enabled": True}
    main.eod_square_off(ctx)
    recorded = ctx["risk"].record_pnl.call_args.args[0]
    assert 450.0 < recorded < 500.0


# ── Liquidity guard (SCRUM-66) ────────────────────────────────────────────────

def test_spread_ok_when_tight():
    cfg = {"risk": {"max_spread_pct": 0.15}}
    quote = {"ltp": 1000.0, "bid": 999.5, "ask": 1000.5}  # 0.1% spread
    assert main._spread_ok("X", quote, cfg) is True


def test_spread_blocked_when_wide():
    cfg = {"risk": {"max_spread_pct": 0.15}}
    quote = {"ltp": 1000.0, "bid": 998.0, "ask": 1002.0}  # 0.4% spread
    assert main._spread_ok("X", quote, cfg) is False


def test_spread_ok_when_no_depth_data():
    cfg = {"risk": {"max_spread_pct": 0.15}}
    quote = {"ltp": 1000.0}  # streamer quote — no bid/ask
    assert main._spread_ok("X", quote, cfg) is True


def test_spread_ok_when_not_configured():
    cfg = {"risk": {}}
    quote = {"ltp": 1000.0, "bid": 990.0, "ask": 1010.0}
    assert main._spread_ok("X", quote, cfg) is True


def test_scan_skips_symbol_with_wide_spread():
    import pandas as pd
    ctx = _make_ctx(
        quotes={"RELIANCE": {"ltp": 2850.0, "bid": 2840.0, "ask": 2860.0},  # ~0.7%
                "TCS": {"ltp": 3500.0}},
        candles=pd.DataFrame({"c": [1]}),
        signal_direction="BUY",
    )
    ctx["cfg"]["risk"]["max_spread_pct"] = 0.15
    ctx["_mock_signal"].direction = "BUY"
    with patch("main.generate_signal", return_value=ctx["_mock_signal"]) as mock_gen:
        main._scan_entries(ctx)
    called_symbols = [c.args[0] for c in mock_gen.call_args_list]
    assert "RELIANCE" not in called_symbols  # blocked by spread guard
    assert "TCS" in called_symbols           # no depth data — allowed


# ── Entry time window (SCRUM-68) ──────────────────────────────────────────────

def _at_time(hour, minute):
    """Patch main.datetime so now() returns the given wall-clock time."""
    fake_now = MagicMock()
    fake_now.time.return_value = datetime(2026, 7, 3, hour, minute).time()
    dt = MagicMock(wraps=datetime)
    dt.now.return_value = fake_now
    return patch("main.datetime", dt)


def test_entry_window_open_inside():
    cfg = {"trading": {"entry_start_time": "09:45", "entry_end_time": "14:30"}}
    with _at_time(11, 0):
        assert main._within_entry_window(cfg) is True


def test_entry_window_closed_before_start():
    cfg = {"trading": {"entry_start_time": "09:45", "entry_end_time": "14:30"}}
    with _at_time(9, 20):
        assert main._within_entry_window(cfg) is False


def test_entry_window_closed_after_end():
    cfg = {"trading": {"entry_start_time": "09:45", "entry_end_time": "14:30"}}
    with _at_time(15, 0):
        assert main._within_entry_window(cfg) is False


def test_entry_window_always_open_when_unconfigured():
    cfg = {"trading": {}}
    assert main._within_entry_window(cfg) is True


def test_scan_skips_entries_outside_window():
    ctx = _make_ctx(quotes={"RELIANCE": {"ltp": 2850.0}})
    ctx["cfg"]["trading"]["entry_start_time"] = "09:45"
    ctx["cfg"]["trading"]["entry_end_time"] = "14:30"
    with _at_time(15, 0):
        main._scan_entries(ctx)
    ctx["fetcher"].get_quotes.assert_not_called()


# ── Market regime filter (SCRUM-67) ───────────────────────────────────────────

def test_get_regime_none_when_disabled():
    ctx = _make_ctx()
    assert main._get_regime(ctx) is None


def test_get_regime_none_when_index_data_unavailable():
    ctx = _make_ctx()
    ctx["cfg"]["strategy"]["regime_filter_enabled"] = True
    ctx["fetcher"].get_candles.return_value = None
    assert main._get_regime(ctx) is None  # fail-open


def test_get_regime_returns_market_regime():
    import pandas as pd
    ctx = _make_ctx()
    ctx["cfg"]["strategy"]["regime_filter_enabled"] = True
    ctx["fetcher"].get_candles.return_value = pd.DataFrame({"close": [1.0]})
    with patch("main.market_regime", return_value="BULLISH"):
        assert main._get_regime(ctx) == "BULLISH"


def test_scan_no_entries_in_neutral_regime():
    import pandas as pd
    ctx = _make_ctx(
        quotes={"RELIANCE": {"ltp": 2850.0}, "TCS": {"ltp": 3500.0}},
        candles=pd.DataFrame({"c": [1]}),
        signal_direction="BUY",
    )
    ctx["cfg"]["strategy"]["regime_filter_enabled"] = True
    with patch("main._get_regime", return_value="NEUTRAL"), \
         patch("main.generate_signal", return_value=ctx["_mock_signal"]) as mock_gen:
        main._scan_entries(ctx)
    mock_gen.assert_not_called()
    ctx["executor"].place_order.assert_not_called()


def test_scan_blocks_buy_signal_in_bearish_regime():
    import pandas as pd
    ctx = _make_ctx(
        quotes={"RELIANCE": {"ltp": 2850.0}, "TCS": {"ltp": 3500.0}},
        candles=pd.DataFrame({"c": [1]}),
        signal_direction="BUY",
    )
    ctx["_mock_signal"].direction = "BUY"
    with patch("main._get_regime", return_value="BEARISH"), \
         patch("main.generate_signal", return_value=ctx["_mock_signal"]):
        main._scan_entries(ctx)
    ctx["executor"].place_order.assert_not_called()


def test_scan_allows_buy_signal_in_bullish_regime():
    import pandas as pd
    ctx = _make_ctx(
        quotes={"RELIANCE": {"ltp": 2850.0}, "TCS": {"ltp": 3500.0}},
        candles=pd.DataFrame({"c": [1]}),
        signal_direction="BUY",
    )
    ctx["_mock_signal"].direction = "BUY"
    with patch("main._get_regime", return_value="BULLISH"), \
         patch("main.generate_signal", return_value=ctx["_mock_signal"]):
        main._scan_entries(ctx)
    ctx["executor"].place_order.assert_called_once()


# ── Crash recovery (state store) ──────────────────────────────────────────────

def test_save_state_passes_counters_and_positions():
    pos = _make_position()
    ctx = _make_ctx(open_positions=[pos])
    ctx["risk"]._daily_pnl = -1500.0
    ctx["risk"]._trades_today = 3
    main._save_state(ctx)
    ctx["state"].save.assert_called_once_with(-1500.0, 3, [pos])


def test_startup_restores_same_day_state():
    saved = {"daily_pnl": -2000.0, "trades_today": 5, "positions": [_make_position()]}
    mock_state = MagicMock()
    mock_state.load.return_value = saved
    mock_risk = MagicMock()
    mock_positions = MagicMock()
    with patch("main.load_dotenv"), \
         patch("main.load_config", return_value=_make_ctx()["cfg"]), \
         patch("main.setup_logging"), \
         patch("main.load_kite_session", return_value=MagicMock()), \
         patch("main.AlertManager", return_value=MagicMock()), \
         patch("main.DataFetcher") as MockFetcher, \
         patch("main.DataStreamer", return_value=MagicMock()), \
         patch("main.OrderExecutor", return_value=MagicMock()), \
         patch("main.RiskManager", return_value=mock_risk), \
         patch("main.PositionManager", return_value=mock_positions), \
         patch("main.StateStore", return_value=mock_state), \
         patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "123"}):
        mock_fetcher = MagicMock()
        mock_fetcher.load_instruments.return_value = True
        MockFetcher.return_value = mock_fetcher
        main.startup()
    mock_risk.restore_counters.assert_called_once_with(-2000.0, 5)
    mock_positions.restore.assert_called_once_with(saved["positions"])


def test_startup_no_restore_when_no_saved_state():
    mock_state = MagicMock()
    mock_state.load.return_value = None
    mock_risk = MagicMock()
    with patch("main.load_dotenv"), \
         patch("main.load_config", return_value=_make_ctx()["cfg"]), \
         patch("main.setup_logging"), \
         patch("main.load_kite_session", return_value=MagicMock()), \
         patch("main.AlertManager", return_value=MagicMock()), \
         patch("main.DataFetcher") as MockFetcher, \
         patch("main.DataStreamer", return_value=MagicMock()), \
         patch("main.OrderExecutor", return_value=MagicMock()), \
         patch("main.RiskManager", return_value=mock_risk), \
         patch("main.PositionManager", return_value=MagicMock()), \
         patch("main.StateStore", return_value=mock_state), \
         patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "123"}):
        mock_fetcher = MagicMock()
        mock_fetcher.load_instruments.return_value = True
        MockFetcher.return_value = mock_fetcher
        main.startup()
    mock_risk.restore_counters.assert_not_called()


def test_run_saves_state_on_shutdown():
    ctx = _make_ctx()
    ctx["risk"].is_market_open.return_value = False
    ctx["positions"].is_square_off_time.return_value = False
    with patch("main.startup", return_value=ctx), \
         patch("main.trading_cycle"), \
         patch("main.eod_square_off"), \
         patch("main._send_daily_summary"), \
         patch("main.TelegramController", return_value=MagicMock()), \
         patch("main.time.sleep", side_effect=KeyboardInterrupt):
        main.run()
    ctx["state"].save.assert_called()


# ── Watchdog exit codes ───────────────────────────────────────────────────────

def test_run_returns_zero_on_clean_shutdown():
    ctx = _make_ctx()
    ctx["risk"].is_market_open.return_value = False
    ctx["positions"].is_square_off_time.return_value = False
    with patch("main.startup", return_value=ctx), \
         patch("main.trading_cycle"), \
         patch("main.eod_square_off"), \
         patch("main._send_daily_summary"), \
         patch("main.TelegramController", return_value=MagicMock()), \
         patch("main.time.sleep", side_effect=KeyboardInterrupt):
        assert main.run() == 0


def test_run_returns_one_on_unhandled_exception():
    ctx = _make_ctx()
    ctx["risk"].is_market_open.return_value = True
    with patch("main.startup", return_value=ctx), \
         patch("main.trading_cycle", side_effect=RuntimeError("boom")), \
         patch("main.eod_square_off"), \
         patch("main._send_daily_summary"), \
         patch("main.TelegramController", return_value=MagicMock()):
        assert main.run() == 1


# ── Heartbeat ─────────────────────────────────────────────────────────────────

def test_heartbeat_fires_after_interval():
    ctx = _make_ctx()
    hb = {"last": 0.0}
    with patch("main.time.monotonic", return_value=10_000.0):
        main._maybe_heartbeat(ctx, hb)
    ctx["alert"].send_raw.assert_called_once()
    text = ctx["alert"].send_raw.call_args.args[0]
    assert "Heartbeat" in text
    assert "0 open positions" in text
    assert hb["last"] == 10_000.0


def test_heartbeat_does_not_fire_before_interval():
    ctx = _make_ctx()
    hb = {"last": 9_000.0}  # 1000s ago < 3600s interval
    with patch("main.time.monotonic", return_value=10_000.0):
        main._maybe_heartbeat(ctx, hb)
    ctx["alert"].send_raw.assert_not_called()


def test_heartbeat_reports_positions_and_streamer():
    pos = _make_position()
    ctx = _make_ctx(open_positions=[pos])
    ctx["streamer"].is_connected = True
    hb = {"last": 0.0}
    with patch("main.time.monotonic", return_value=10_000.0):
        main._maybe_heartbeat(ctx, hb)
    text = ctx["alert"].send_raw.call_args.args[0]
    assert "1 open positions" in text
    assert "streamer connected" in text
