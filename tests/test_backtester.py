from unittest.mock import patch

import pandas as pd
import pytest

from src.backtester import Backtester, BacktestResult, BacktestTrade, format_report
from src.strategy import TradeSignal


@pytest.fixture
def cfg():
    return {
        "trading": {"square_off_time": "15:15"},
        "strategy": {"ema_fast": 9, "ema_slow": 21, "ema_crossover_lookback": 3,
                     "rsi_period": 14, "rsi_entry_threshold": 60,
                     "volume_sma_period": 20, "volume_multiplier": 1.5},
        "risk": {"total_capital": 500000, "max_risk_per_trade_pct": 1.0,
                 "max_open_positions": 3, "max_position_size_pct": 20.0,
                 "order_value_cap": 120000, "max_daily_loss": 10000,
                 "max_trades_per_day": 8, "trailing_sl_enabled": False,
                 "trailing_sl_activation_pct": 1.0, "trailing_sl_step_pct": 0.5},
        "costs": {"enabled": False},  # keep P&L assertions exact; costs tested separately
    }


def _candles(symbol_rows, date="2026-07-01", start="10:00"):
    """Build a candle DataFrame from [(open, high, low, close, volume), ...] 5 min apart."""
    start_ts = pd.Timestamp(f"{date} {start}")
    rows = []
    for i, (o, h, l, c, v) in enumerate(symbol_rows):
        rows.append({"timestamp": start_ts + pd.Timedelta(minutes=5 * i),
                     "open": o, "high": h, "low": l, "close": c, "volume": v})
    return pd.DataFrame(rows)


def _signal_on_first_candle(direction="BUY", entry=100.0, sl=99.0, target=102.0):
    """Return a generate_signal replacement that signals once, then HOLDs."""
    state = {"fired": False}

    def fake(symbol, df, cfg):
        if not state["fired"]:
            state["fired"] = True
            return TradeSignal(direction, symbol, entry, sl, target, "test")
        return TradeSignal("HOLD", symbol, 0.0, 0.0, 0.0, "test")

    return fake


HOLD = lambda symbol, df, cfg: TradeSignal("HOLD", symbol, 0.0, 0.0, 0.0, "test")


# ── Metrics (BacktestResult.from_trades) ──────────────────────────────────────

def _trade(pnl, exit_minute=0):
    return BacktestTrade("X", "BUY", 10, 100.0, 100.0 + pnl / 10,
                         pd.Timestamp("2026-07-01 10:00"),
                         pd.Timestamp("2026-07-01 10:05") + pd.Timedelta(minutes=exit_minute),
                         pnl, "test")


def test_metrics_win_rate_and_net_pnl():
    r = BacktestResult.from_trades([_trade(500, 0), _trade(-200, 5), _trade(300, 10)])
    assert r.total_trades == 3
    assert r.wins == 2 and r.losses == 1
    assert r.win_rate == pytest.approx(66.67)
    assert r.net_pnl == 600.0


def test_metrics_profit_factor():
    r = BacktestResult.from_trades([_trade(600, 0), _trade(-300, 5)])
    assert r.gross_profit == 600.0
    assert r.gross_loss == 300.0
    assert r.profit_factor == 2.0


def test_metrics_profit_factor_no_losses_is_inf():
    r = BacktestResult.from_trades([_trade(500, 0)])
    assert r.profit_factor == float("inf")


def test_metrics_max_drawdown():
    # equity: +500, -300 (dd 300), +100 (dd 200), -600 (dd 800)
    r = BacktestResult.from_trades([
        _trade(500, 0), _trade(-300, 5), _trade(100, 10), _trade(-600, 15),
    ])
    assert r.max_drawdown == 800.0


def test_metrics_empty_trades():
    r = BacktestResult.from_trades([])
    assert r.total_trades == 0
    assert r.win_rate == 0.0
    assert r.profit_factor == 0.0
    assert r.max_drawdown == 0.0


def test_metrics_avg_win_and_loss():
    r = BacktestResult.from_trades([_trade(400, 0), _trade(200, 5), _trade(-150, 10)])
    assert r.avg_win == 300.0
    assert r.avg_loss == 150.0


# ── Entry & exit simulation ───────────────────────────────────────────────────

def test_buy_target_hit(cfg):
    candles = {"X": _candles([
        (100, 100.5, 99.5, 100, 1000),   # signal fires here, entry @ 100
        (100, 103.0, 100.0, 102.5, 1000),  # high crosses target 102
    ])}
    with patch("src.backtester.generate_signal", side_effect=_signal_on_first_candle()):
        result = Backtester(cfg).run(candles)
    assert result.total_trades == 1
    t = result.trades[0]
    assert t.exit_reason == "target_hit"
    assert t.exit_price == 102.0
    assert t.pnl > 0


def test_buy_sl_hit(cfg):
    candles = {"X": _candles([
        (100, 100.5, 99.5, 100, 1000),
        (100, 100.5, 98.0, 98.5, 1000),  # low crosses SL 99
    ])}
    with patch("src.backtester.generate_signal", side_effect=_signal_on_first_candle()):
        result = Backtester(cfg).run(candles)
    t = result.trades[0]
    assert t.exit_reason == "sl_hit"
    assert t.exit_price == 99.0
    assert t.pnl < 0


def test_sl_priority_when_both_hit_same_candle(cfg):
    candles = {"X": _candles([
        (100, 100.5, 99.5, 100, 1000),
        (100, 105.0, 95.0, 100.0, 1000),  # both SL 99 and target 102 inside candle
    ])}
    with patch("src.backtester.generate_signal", side_effect=_signal_on_first_candle()):
        result = Backtester(cfg).run(candles)
    assert result.trades[0].exit_reason == "sl_hit"


def test_sell_direction_target_hit(cfg):
    candles = {"X": _candles([
        (100, 100.5, 99.5, 100, 1000),
        (100, 100.5, 97.5, 98.0, 1000),  # low crosses SELL target 98
    ])}
    fake = _signal_on_first_candle("SELL", entry=100.0, sl=101.0, target=98.0)
    with patch("src.backtester.generate_signal", side_effect=fake):
        result = Backtester(cfg).run(candles)
    t = result.trades[0]
    assert t.direction == "SELL"
    assert t.exit_reason == "target_hit"
    assert t.pnl > 0


def test_eod_square_off(cfg):
    candles = {"X": _candles([
        (100, 100.5, 99.5, 100, 1000),      # 15:05 — entry
        (100, 100.6, 99.9, 100.2, 1000),    # 15:10 — no exit
        (100, 100.7, 100.0, 100.5, 1000),   # 15:15 — square-off time
    ], start="15:05")}
    with patch("src.backtester.generate_signal", side_effect=_signal_on_first_candle()):
        result = Backtester(cfg).run(candles)
    t = result.trades[0]
    assert t.exit_reason == "eod_square_off"
    assert t.exit_price == 100.5


def test_open_position_closed_at_end_of_data(cfg):
    candles = {"X": _candles([
        (100, 100.5, 99.5, 100, 1000),
        (100, 100.6, 99.9, 100.3, 1000),  # no SL/target touch, data ends
    ])}
    with patch("src.backtester.generate_signal", side_effect=_signal_on_first_candle()):
        result = Backtester(cfg).run(candles)
    assert result.trades[0].exit_reason == "end_of_data"


def test_hold_produces_no_trades(cfg):
    candles = {"X": _candles([(100, 101, 99, 100, 1000)] * 5)}
    with patch("src.backtester.generate_signal", side_effect=HOLD):
        result = Backtester(cfg).run(candles)
    assert result.total_trades == 0


# ── Risk rules ────────────────────────────────────────────────────────────────

def test_quantity_uses_risk_formula(cfg):
    # risk/share = 1.0, max risk = 1% of 500k = 5000 → qty 5000, capped by
    # max_pos 100k/100 = 1000 shares
    candles = {"X": _candles([
        (100, 100.5, 99.5, 100, 1000),
        (100, 103.0, 100.0, 102.5, 1000),
    ])}
    with patch("src.backtester.generate_signal", side_effect=_signal_on_first_candle()):
        result = Backtester(cfg).run(candles)
    assert result.trades[0].quantity == 1000


def test_max_open_positions_respected(cfg):
    cfg["risk"]["max_open_positions"] = 1
    always_buy = lambda symbol, df, cfg_: TradeSignal("BUY", symbol, 100.0, 99.0, 200.0, "t")
    rows = [(100, 100.5, 99.5, 100, 1000)] * 4
    candles = {"A": _candles(rows), "B": _candles(rows)}
    with patch("src.backtester.generate_signal", side_effect=always_buy):
        result = Backtester(cfg).run(candles)
    # Only one position can ever be open; it never exits until end_of_data
    assert result.total_trades == 1


def test_max_trades_per_day_halts_entries(cfg):
    cfg["risk"]["max_trades_per_day"] = 2
    always_buy = lambda symbol, df, cfg_: TradeSignal("BUY", symbol, 100.0, 99.0, 100.4, "t")
    # target 100.4 hits every candle (high 100.5) → rapid churn
    rows = [(100, 100.5, 99.5, 100, 1000)] * 10
    candles = {"A": _candles(rows)}
    with patch("src.backtester.generate_signal", side_effect=always_buy):
        result = Backtester(cfg).run(candles)
    assert result.total_trades == 2


def test_daily_loss_circuit_breaker_halts_entries(cfg):
    cfg["risk"]["max_daily_loss"] = 500
    always_buy = lambda symbol, df, cfg_: TradeSignal("BUY", symbol, 100.0, 99.0, 200.0, "t")
    # every trade loses: SL hits next candle. qty=1000 → loss 1000 per trade > 500 cap
    rows = [(100, 100.5, 99.5, 100, 1000), (100, 100.2, 98.5, 99.0, 1000)] * 5
    candles = {"A": _candles(rows)}
    with patch("src.backtester.generate_signal", side_effect=always_buy):
        result = Backtester(cfg).run(candles)
    # first trade loses 1000 ≥ 500 → halted for the day, no more entries
    assert result.total_trades == 1


def test_daily_counters_reset_next_day(cfg):
    cfg["risk"]["max_trades_per_day"] = 1
    always_buy = lambda symbol, df, cfg_: TradeSignal("BUY", symbol, 100.0, 99.0, 100.4, "t")
    day1 = _candles([(100, 100.5, 99.5, 100, 1000)] * 3, date="2026-07-01")
    day2 = _candles([(100, 100.5, 99.5, 100, 1000)] * 3, date="2026-07-02")
    candles = {"A": pd.concat([day1, day2], ignore_index=True)}
    with patch("src.backtester.generate_signal", side_effect=always_buy):
        result = Backtester(cfg).run(candles)
    assert result.total_trades == 2  # one per day


def test_order_value_cap_blocks_entry(cfg):
    cfg["risk"]["order_value_cap"] = 50  # absurdly low — blocks everything
    always_buy = lambda symbol, df, cfg_: TradeSignal("BUY", symbol, 100.0, 99.0, 102.0, "t")
    candles = {"A": _candles([(100, 100.5, 99.5, 100, 1000)] * 3)}
    with patch("src.backtester.generate_signal", side_effect=always_buy):
        result = Backtester(cfg).run(candles)
    assert result.total_trades == 0


def test_one_entry_per_cycle(cfg):
    always_buy = lambda symbol, df, cfg_: TradeSignal("BUY", symbol, 100.0, 99.0, 200.0, "t")
    rows = [(100, 100.4, 99.5, 100, 1000)]  # single timestamp
    candles = {"A": _candles(rows), "B": _candles(rows), "C": _candles(rows)}
    with patch("src.backtester.generate_signal", side_effect=always_buy):
        result = Backtester(cfg).run(candles)
    assert result.total_trades == 1  # only one entry on the single shared timestamp


# ── Trailing SL ───────────────────────────────────────────────────────────────

def test_trailing_sl_locks_in_profit(cfg):
    cfg["risk"]["trailing_sl_enabled"] = True
    candles = {"X": _candles([
        (100, 100.5, 99.5, 100, 1000),      # entry @ 100, SL 97, target 110
        (100, 102.2, 100.0, 102.0, 1000),   # +2% close → trailing arms next candle
        (102, 102.5, 100.4, 100.5, 1000),   # trailing SL (>=100) hit on the dip
    ])}
    fake = _signal_on_first_candle(entry=100.0, sl=97.0, target=110.0)
    with patch("src.backtester.generate_signal", side_effect=fake):
        result = Backtester(cfg).run(candles)
    t = result.trades[0]
    assert t.exit_reason == "sl_hit"
    assert t.exit_price >= 100.0  # trailing moved SL to breakeven or better
    assert t.pnl >= 0


# ── Window & report ───────────────────────────────────────────────────────────

def test_window_limits_dataframe_passed_to_strategy(cfg):
    seen_lengths = []

    def spy(symbol, df, cfg_):
        seen_lengths.append(len(df))
        return TradeSignal("HOLD", symbol, 0.0, 0.0, 0.0, "t")

    candles = {"X": _candles([(100, 101, 99, 100, 1000)] * 30)}
    with patch("src.backtester.generate_signal", side_effect=spy):
        Backtester(cfg, window=10).run(candles)
    assert max(seen_lengths) == 10


def test_entry_window_blocks_entries_outside(cfg):
    cfg["trading"]["entry_start_time"] = "09:45"
    cfg["trading"]["entry_end_time"] = "14:30"
    always_buy = lambda symbol, df, cfg_: TradeSignal("BUY", symbol, 100.0, 99.0, 200.0, "t")
    # candles at 09:20 — before the entry window opens
    candles = {"A": _candles([(100, 100.5, 99.5, 100, 1000)] * 3, start="09:20")}
    with patch("src.backtester.generate_signal", side_effect=always_buy):
        result = Backtester(cfg).run(candles)
    assert result.total_trades == 0


def test_entry_window_allows_entries_inside(cfg):
    cfg["trading"]["entry_start_time"] = "09:45"
    cfg["trading"]["entry_end_time"] = "14:30"
    candles = {"A": _candles([
        (100, 100.5, 99.5, 100, 1000),
        (100, 103.0, 100.0, 102.5, 1000),
    ], start="10:00")}
    with patch("src.backtester.generate_signal", side_effect=_signal_on_first_candle()):
        result = Backtester(cfg).run(candles)
    assert result.total_trades == 1


def test_regime_filter_blocks_buy_in_bearish_market(cfg):
    cfg["strategy"]["regime_filter_enabled"] = True
    always_buy = lambda symbol, df, cfg_: TradeSignal("BUY", symbol, 100.0, 99.0, 200.0, "t")
    rows = [(100, 100.5, 99.5, 100, 1000)] * 3
    candles = {"A": _candles(rows)}
    index = _candles(rows)  # same timestamps
    with patch("src.backtester.generate_signal", side_effect=always_buy), \
         patch("src.backtester.market_regime", return_value="BEARISH"):
        result = Backtester(cfg).run(candles, index_candles=index)
    assert result.total_trades == 0


def test_regime_filter_allows_buy_in_bullish_market(cfg):
    cfg["strategy"]["regime_filter_enabled"] = True
    candles = {"A": _candles([
        (100, 100.5, 99.5, 100, 1000),
        (100, 103.0, 100.0, 102.5, 1000),
    ])}
    index = _candles([(22000, 22010, 21990, 22000, 0)] * 2)
    with patch("src.backtester.generate_signal", side_effect=_signal_on_first_candle()), \
         patch("src.backtester.market_regime", return_value="BULLISH"):
        result = Backtester(cfg).run(candles, index_candles=index)
    assert result.total_trades == 1


def test_regime_filter_off_without_index_candles(cfg):
    cfg["strategy"]["regime_filter_enabled"] = True
    candles = {"A": _candles([
        (100, 100.5, 99.5, 100, 1000),
        (100, 103.0, 100.0, 102.5, 1000),
    ])}
    with patch("src.backtester.generate_signal", side_effect=_signal_on_first_candle()):
        result = Backtester(cfg).run(candles)  # no index data → filter inactive
    assert result.total_trades == 1


def test_costs_subtracted_from_trade_pnl(cfg):
    cfg["costs"] = {"enabled": True}
    candles = {"X": _candles([
        (100, 100.5, 99.5, 100, 1000),
        (100, 103.0, 100.0, 102.5, 1000),  # target 102 hit
    ])}
    with patch("src.backtester.generate_signal", side_effect=_signal_on_first_candle()):
        result = Backtester(cfg).run(candles)
    t = result.trades[0]
    assert t.costs > 0
    # gross = (102-100) * 1000 = 2000; net must be lower by exactly the costs
    assert t.pnl == pytest.approx(2000 - t.costs, abs=0.02)


def test_format_report_contains_key_metrics():
    r = BacktestResult.from_trades([_trade(500, 0), _trade(-200, 5)])
    report = format_report(r)
    assert "Win rate" in report
    assert "Profit factor" in report
    assert "Max drawdown" in report
    assert "Rs.300" in report  # net pnl
