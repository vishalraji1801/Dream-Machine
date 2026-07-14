"""
Backtesting engine.
Replays historical 5-min candles through the live strategy and risk rules,
simulating entries, SL/target exits, trailing SL, EOD square-off and daily
circuit breakers. Reports win rate, profit factor, max drawdown and net P&L.

Simulation notes:
- Entry fills at the close of the signal candle (mirrors live LIMIT entry
  on the completed candle's close).
- SL/target are checked against each candle's high/low. If both fall inside
  the same candle, SL is assumed to hit first (conservative).
- Trailing SL advances using the PREVIOUS candle's close (no look-ahead).
- When the daily circuit breaker trips, exits keep working (as Kite GTT
  would) but no new entries are taken and trailing stops advancing.
"""
from dataclasses import dataclass, field
from datetime import time as dtime
from typing import Optional

import pandas as pd

from src.costs import estimate_intraday_costs, trade_leg_values
from src.logger import get_logger
from src.strategy import generate_signal, market_regime

logger = get_logger("backtester")


@dataclass
class BacktestTrade:
    symbol: str
    direction: str
    quantity: int
    entry_price: float
    exit_price: float
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    pnl: float              # net of estimated transaction costs
    exit_reason: str
    costs: float = 0.0      # estimated charges for the round trip


@dataclass
class BacktestResult:
    trades: list = field(default_factory=list)
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    net_pnl: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    profit_factor: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    max_drawdown: float = 0.0

    @classmethod
    def from_trades(cls, trades: list) -> "BacktestResult":
        r = cls(trades=list(trades))
        r.total_trades = len(trades)
        if not trades:
            return r

        winners = [t for t in trades if t.pnl > 0]
        losers = [t for t in trades if t.pnl <= 0]
        r.wins = len(winners)
        r.losses = len(losers)
        r.win_rate = round(100 * r.wins / r.total_trades, 2)
        r.net_pnl = round(sum(t.pnl for t in trades), 2)
        r.gross_profit = round(sum(t.pnl for t in winners), 2)
        r.gross_loss = round(abs(sum(t.pnl for t in losers)), 2)
        r.profit_factor = (
            round(r.gross_profit / r.gross_loss, 2) if r.gross_loss > 0
            else float("inf") if r.gross_profit > 0 else 0.0
        )
        r.avg_win = round(r.gross_profit / r.wins, 2) if r.wins else 0.0
        r.avg_loss = round(r.gross_loss / r.losses, 2) if r.losses else 0.0

        equity = peak = drawdown = 0.0
        for t in sorted(trades, key=lambda t: t.exit_time):
            equity += t.pnl
            peak = max(peak, equity)
            drawdown = max(drawdown, peak - equity)
        r.max_drawdown = round(drawdown, 2)
        return r


@dataclass
class _OpenPosition:
    symbol: str
    direction: str
    quantity: int
    entry_price: float
    stop_loss: float
    target: float
    entry_time: pd.Timestamp
    prev_close: float  # previous candle close, used for trailing SL


class Backtester:
    """Simulates the live bot's trading rules over historical candles."""

    def __init__(self, cfg: dict, window: int = 60):
        self._cfg = cfg
        self._strategy_cfg = cfg["strategy"]
        self._r = cfg["risk"]
        self._window = window
        h, m = map(int, cfg["trading"]["square_off_time"].split(":"))
        self._square_off = dtime(h, m)

        def _parse(key):
            v = cfg["trading"].get(key)
            return dtime(*map(int, v.split(":"))) if v else None
        self._entry_start = _parse("entry_start_time")
        self._entry_end = _parse("entry_end_time")

        bt = cfg.get("backtest", {})
        self._fill_mode = bt.get("fill_mode", "close")
        self._bt_slippage = bt.get("slippage_pct", 0.0)

    # ── Public API ────────────────────────────────────────────────────────────

    def run(self, candles: dict[str, pd.DataFrame],
            index_candles: Optional[pd.DataFrame] = None) -> BacktestResult:
        """
        candles: {symbol: DataFrame[timestamp, open, high, low, close, volume]},
        each sorted chronologically. index_candles: optional index (e.g. NIFTY 50)
        candles for the regime filter — applied only when regime_filter_enabled.
        Returns aggregated BacktestResult.
        """
        indexed = {
            sym: {row.timestamp: i for i, row in enumerate(df.itertuples())}
            for sym, df in candles.items()
        }
        timestamps = sorted({ts for m in indexed.values() for ts in m})

        regime_on = (self._strategy_cfg.get("regime_filter_enabled")
                     and index_candles is not None and not index_candles.empty)
        idx_map = ({row.timestamp: i for i, row in enumerate(index_candles.itertuples())}
                   if regime_on else {})
        regime = None  # last computed regime, carried forward between index candles

        trades: list[BacktestTrade] = []
        open_pos: dict[str, _OpenPosition] = {}
        day = None
        daily_pnl = 0.0
        trades_today = 0
        halted = False

        for ts in timestamps:
            if day != ts.date():
                day = ts.date()
                daily_pnl = 0.0
                trades_today = 0
                halted = False

            # 1. Manage open positions (trailing + SL/target)
            for sym in list(open_pos):
                if ts not in indexed[sym]:
                    continue
                i = indexed[sym][ts]
                row = candles[sym].iloc[i]
                pos = open_pos[sym]

                if not halted:
                    self._update_trailing(pos)

                exit_price, reason = self._check_intrabar_exit(pos, row)
                if exit_price is not None:
                    pnl = self._close(trades, open_pos, pos, exit_price, ts, reason)
                    daily_pnl += pnl
                else:
                    pos.prev_close = row["close"]

            # 2. Circuit breakers (same rules as RiskManager)
            loss = abs(min(daily_pnl, 0.0))
            if not halted and (loss >= self._r["max_daily_loss"]
                               or trades_today >= self._r["max_trades_per_day"]):
                halted = True

            # 3. EOD square-off
            if ts.time() >= self._square_off:
                for sym in list(open_pos):
                    pos = open_pos[sym]
                    close_price = self._last_close(candles[sym], indexed[sym], ts, pos.prev_close)
                    pnl = self._close(trades, open_pos, pos, close_price, ts, "eod_square_off")
                    daily_pnl += pnl
                continue  # no entries at/after square-off

            # 4. Entry scan — one entry per cycle, mirrors live _scan_entries
            if halted or len(open_pos) >= self._r["max_open_positions"]:
                continue
            if self._entry_start and not (self._entry_start <= ts.time() <= self._entry_end):
                continue  # outside entry window — positions still managed above
            if regime_on and ts in idx_map:
                i = idx_map[ts]
                idx_win = index_candles.iloc[max(0, i + 1 - self._window): i + 1]
                regime = market_regime(idx_win, self._strategy_cfg)
            if regime == "NEUTRAL":
                continue
            for sym, df in candles.items():
                if sym in open_pos or ts not in indexed[sym]:
                    continue
                i = indexed[sym][ts]
                win_df = df.iloc[max(0, i + 1 - self._window): i + 1]
                signal = generate_signal(sym, win_df, self._strategy_cfg)
                if signal.direction == "HOLD":
                    continue
                if regime and ((signal.direction == "BUY" and regime != "BULLISH")
                               or (signal.direction == "SELL" and regime != "BEARISH")):
                    continue
                # Honest fills (SCRUM-82): next-candle open instead of signal close.
                entry_price = signal.entry_price
                if self._fill_mode == "next_open":
                    if i + 1 >= len(df):
                        continue  # no next candle to fill against
                    nxt = df.iloc[i + 1]["open"]
                    slip = self._bt_slippage / 100
                    entry_price = round(nxt * (1 + slip) if signal.direction == "BUY"
                                        else nxt * (1 - slip), 2)
                qty = self._calculate_quantity(entry_price, signal.stop_loss)
                if qty <= 0:
                    continue
                # sizing already shrinks to fit order_value_cap and max_position;
                # no skip needed — a high-priced stock just takes a smaller size.
                open_pos[sym] = _OpenPosition(
                    symbol=sym, direction=signal.direction, quantity=qty,
                    entry_price=entry_price, stop_loss=signal.stop_loss,
                    target=signal.target, entry_time=ts,
                    prev_close=entry_price,
                )
                trades_today += 1
                break  # one entry per cycle

        # Close anything still open at the end of the data
        for sym in list(open_pos):
            pos = open_pos[sym]
            last_ts = max(indexed[sym])
            close_price = candles[sym].iloc[indexed[sym][last_ts]]["close"]
            self._close(trades, open_pos, pos, close_price, last_ts, "end_of_data")

        result = BacktestResult.from_trades(trades)
        logger.info(
            f"Backtest complete: {result.total_trades} trades | "
            f"win rate {result.win_rate}% | net P&L Rs.{result.net_pnl}"
        )
        return result

    # ── Simulation helpers ────────────────────────────────────────────────────

    def _check_intrabar_exit(self, pos: _OpenPosition, row) -> tuple[Optional[float], str]:
        """SL checked before target inside the same candle (conservative)."""
        if pos.direction == "BUY":
            if row["low"] <= pos.stop_loss:
                return pos.stop_loss, "sl_hit"
            if row["high"] >= pos.target:
                return pos.target, "target_hit"
        else:
            if row["high"] >= pos.stop_loss:
                return pos.stop_loss, "sl_hit"
            if row["low"] <= pos.target:
                return pos.target, "target_hit"
        return None, ""

    def _update_trailing(self, pos: _OpenPosition) -> None:
        """Mirror PositionManager.update_trailing_sl using previous candle close."""
        if not self._r["trailing_sl_enabled"]:
            return
        act = self._r["trailing_sl_activation_pct"] / 100
        step = self._r["trailing_sl_step_pct"] / 100
        price = pos.prev_close

        if pos.direction == "BUY":
            profit = (price - pos.entry_price) / pos.entry_price
            if profit < act:
                return
            steps = int((profit - act) / step)
            new_sl = max(round(pos.entry_price * (1 + steps * step), 2), pos.entry_price)
            pos.stop_loss = max(pos.stop_loss, new_sl)
        else:
            profit = (pos.entry_price - price) / pos.entry_price
            if profit < act:
                return
            steps = int((profit - act) / step)
            new_sl = min(round(pos.entry_price * (1 - steps * step), 2), pos.entry_price)
            pos.stop_loss = min(pos.stop_loss, new_sl)

    def _calculate_quantity(self, entry_price: float, stop_loss: float) -> int:
        """Same formula as RiskManager.calculate_quantity."""
        risk_per_share = abs(entry_price - stop_loss)
        if risk_per_share <= 0:
            return 0
        max_risk = self._r["total_capital"] * self._r["max_risk_per_trade_pct"] / 100
        qty = int(max_risk / risk_per_share)
        # shrink to the tighter of max-position-value and per-order value cap
        value_cap = min(self._r["total_capital"] * self._r["max_position_size_pct"] / 100,
                        self._r["order_value_cap"])
        if entry_price > 0 and qty * entry_price > value_cap:
            qty = int(value_cap / entry_price)
        return max(qty, 0)

    @staticmethod
    def _last_close(df: pd.DataFrame, index: dict, ts, fallback: float) -> float:
        if ts in index:
            return df.iloc[index[ts]]["close"]
        return fallback

    def _close(self, trades, open_pos, pos, exit_price, ts, reason) -> float:
        if pos.direction == "BUY":
            gross = (exit_price - pos.entry_price) * pos.quantity
        else:
            gross = (pos.entry_price - exit_price) * pos.quantity
        buy_v, sell_v = trade_leg_values(pos.direction, pos.entry_price,
                                         exit_price, pos.quantity)
        costs = estimate_intraday_costs(buy_v, sell_v, self._cfg)
        pnl = round(gross - costs, 2)
        trades.append(BacktestTrade(
            symbol=pos.symbol, direction=pos.direction, quantity=pos.quantity,
            entry_price=pos.entry_price, exit_price=exit_price,
            entry_time=pos.entry_time, exit_time=ts, pnl=pnl, exit_reason=reason,
            costs=costs,
        ))
        del open_pos[pos.symbol]
        return pnl


def format_report(result: BacktestResult) -> str:
    """Human-readable backtest report for the CLI."""
    lines = [
        "=" * 62,
        " BACKTEST REPORT",
        "=" * 62,
        f" Total trades   : {result.total_trades}",
        f" Wins / Losses  : {result.wins} / {result.losses}",
        f" Win rate       : {result.win_rate}%",
        f" Net P&L        : Rs.{result.net_pnl}",
        f" Gross profit   : Rs.{result.gross_profit}",
        f" Gross loss     : Rs.{result.gross_loss}",
        f" Profit factor  : {result.profit_factor}",
        f" Avg win        : Rs.{result.avg_win}",
        f" Avg loss       : Rs.{result.avg_loss}",
        f" Max drawdown   : Rs.{result.max_drawdown}",
        f" Est. costs     : Rs.{round(sum(t.costs for t in result.trades), 2)}",
        "=" * 62,
    ]
    if result.trades:
        lines.append(" Trades:")
        for t in sorted(result.trades, key=lambda t: t.exit_time):
            lines.append(
                f"  {t.entry_time:%Y-%m-%d %H:%M} {t.direction:<4} {t.symbol:<12} "
                f"qty={t.quantity:<5} entry={t.entry_price:<9.2f} exit={t.exit_price:<9.2f} "
                f"pnl={t.pnl:>10.2f}  {t.exit_reason}"
            )
        lines.append("=" * 62)
    return "\n".join(lines)
