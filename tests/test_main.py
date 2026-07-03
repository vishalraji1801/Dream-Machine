"""
Tests for main.py — startup, trading cycle, EOD square-off, graceful shutdown.
"""
from unittest.mock import MagicMock, patch, call
import pytest

import main
from src.position_manager import Position
from datetime import datetime


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_ctx(
    risk_halted=False,
    circuit_breaker=(False, ""),
    open_positions=None,
    quotes=None,
    candles=None,
    signal_direction="HOLD",
    pre_trade_ok=True,
    margin=100000.0,
):
    cfg = {
        "trading": {"exchange": "NSE", "product_type": "MIS", "watchlist": ["RELIANCE", "TCS"],
                    "square_off_time": "15:15"},
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
    }

    mock_signal = MagicMock()
    mock_signal.direction = signal_direction
    mock_signal.entry_price = 2850.0
    mock_signal.stop_loss = 2821.5
    mock_signal.target = 2907.0

    risk = MagicMock()
    risk.check_circuit_breakers.return_value = circuit_breaker
    risk.check_pre_trade.return_value = (pre_trade_ok, "ok" if pre_trade_ok else "blocked")
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

    alert = MagicMock()
    alert.send.return_value = True

    streamer = MagicMock()
    streamer.is_connected = False  # default: not connected → falls back to REST
    streamer.get_latest_quotes.return_value = quotes

    return {
        "cfg": cfg, "kite": kite, "alert": alert,
        "fetcher": fetcher, "streamer": streamer, "executor": executor,
        "risk": risk, "positions": positions,
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


# ── trading_cycle ─────────────────────────────────────────────────────────────

def test_cycle_skips_on_circuit_breaker():
    ctx = _make_ctx(circuit_breaker=(True, "Daily loss limit hit"))
    main.trading_cycle(ctx)
    ctx["alert"].send.assert_called_once_with("circuit_breaker", reason="Daily loss limit hit")
    ctx["fetcher"].get_quotes.assert_not_called()


def test_cycle_calls_manage_positions_and_scan():
    ctx = _make_ctx(circuit_breaker=(False, ""))
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
         patch("main.time.sleep", side_effect=KeyboardInterrupt):
        main.run()

    ctx["streamer"].disconnect.assert_called_once()


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
