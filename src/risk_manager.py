"""
Risk manager.
Enforces pre-trade checks (margin, position limits, order size) and daily circuit breakers.
All thresholds are read from config.yaml — nothing is hardcoded.
"""
from datetime import datetime, time

from src.logger import get_logger

logger = get_logger("risk_manager")


class RiskManager:
    def __init__(self, cfg: dict):
        self._r = cfg["risk"]
        self._t = cfg["trading"]
        self._sectors = cfg.get("sectors", {})  # {symbol: sector} for the sector cap
        self._daily_pnl: float = 0.0
        self._peak_pnl: float = 0.0
        self._trades_today: int = 0
        self._consecutive_api_errors: int = 0
        self._halted: bool = False

    # ── Daily state mutators ──────────────────────────────────────────────────

    def reset_daily_counters(self) -> None:
        self._daily_pnl = 0.0
        self._trades_today = 0
        self._consecutive_api_errors = 0
        self._halted = False
        logger.info("Daily risk counters reset")

    def restore_counters(self, daily_pnl: float, trades_today: int) -> None:
        """Restore same-day counters from a saved state file (crash recovery)."""
        self._daily_pnl = daily_pnl
        self._trades_today = trades_today
        logger.warning(f"Risk counters restored: P&L Rs.{daily_pnl:.2f}, {trades_today} trades")

    def record_pnl(self, pnl: float) -> None:
        self._daily_pnl += pnl
        self._peak_pnl = max(self._peak_pnl, self._daily_pnl)
        logger.info(f"Daily P&L updated: Rs.{self._daily_pnl:.2f} (peak Rs.{self._peak_pnl:.2f})")

    def record_trade(self) -> None:
        self._trades_today += 1
        logger.info(f"Trade count today: {self._trades_today}")

    def record_api_error(self) -> None:
        self._consecutive_api_errors += 1
        logger.warning(f"Consecutive API errors: {self._consecutive_api_errors}")

    def clear_api_errors(self) -> None:
        self._consecutive_api_errors = 0

    def is_halted(self) -> bool:
        return self._halted

    # ── Circuit breakers ─────────────────────────────────────────────────────

    def check_circuit_breakers(self) -> tuple[bool, str]:
        """Check all daily limits. Returns (ok, reason). Sets halted=True on breach."""
        if self._halted:
            return False, "already_halted"

        loss = abs(min(self._daily_pnl, 0.0))
        if loss >= self._r["max_daily_loss"]:
            return self._halt(f"Daily loss limit reached: Rs.{loss:.2f}")

        if self._trades_today >= self._r["max_trades_per_day"]:
            return self._halt(f"Max trades/day reached: {self._trades_today}")

        if self._consecutive_api_errors >= self._r["max_consecutive_api_errors"]:
            return self._halt(f"Consecutive API errors: {self._consecutive_api_errors}")

        giveback_limit = self._r.get("max_giveback_from_peak", 0)
        if giveback_limit and self._peak_pnl > 0:
            giveback = self._peak_pnl - self._daily_pnl
            if giveback >= giveback_limit:
                return self._halt(
                    f"Drawdown-from-peak kill switch: gave back Rs.{giveback:.2f} "
                    f"from peak Rs.{self._peak_pnl:.2f}")

        return True, ""

    def check_sector_cap(self, symbol: str, open_symbols: list) -> tuple[bool, str]:
        """Block a new entry if its sector already holds max_positions_per_sector (SCRUM-82).
        Prevents 'one trade wearing three hats' (e.g. three private banks at once)."""
        cap = self._r.get("max_positions_per_sector")
        if not cap or not self._sectors:
            return True, ""
        sector = self._sectors.get(symbol)
        if sector is None:
            return True, ""
        held = sum(1 for s in open_symbols if self._sectors.get(s) == sector)
        if held >= cap:
            return False, f"sector cap for {sector} reached ({held})"
        return True, ""

    def _halt(self, reason: str) -> tuple[bool, str]:
        self._halted = True
        logger.critical(f"CIRCUIT BREAKER TRIGGERED: {reason}")
        return False, reason

    # ── Pre-trade checks ─────────────────────────────────────────────────────

    def check_pre_trade(
        self, order_value: float, available_margin: float, open_positions: int
    ) -> tuple[bool, str]:
        """Validate a single trade against all position and margin rules."""
        max_pos_value = self._r["total_capital"] * self._r["max_position_size_pct"] / 100

        checks = [
            (self._halted,                                  "bot_halted"),
            (order_value > self._r["order_value_cap"],      f"order_value {order_value:.0f} > cap {self._r['order_value_cap']}"),
            (order_value > max_pos_value,                   f"order_value {order_value:.0f} > max_position {max_pos_value:.0f}"),
            (open_positions >= self._r["max_open_positions"], f"max_open_positions reached ({open_positions})"),
            (available_margin < self._r["min_margin_threshold"], f"margin {available_margin:.0f} < threshold {self._r['min_margin_threshold']}"),
        ]
        for failed, reason in checks:
            if failed:
                logger.warning(f"Pre-trade BLOCKED: {reason}")
                return False, reason

        logger.info(f"Pre-trade APPROVED | order_value={order_value:.0f} margin={available_margin:.0f} positions={open_positions}")
        return True, ""

    def is_market_open(self) -> bool:
        """True if current time is within configured market hours."""
        now = datetime.now().time()
        open_t = time(*map(int, self._t["market_open"].split(":")))
        close_t = time(*map(int, self._t["square_off_time"].split(":")))
        within = open_t <= now <= close_t
        if not within:
            logger.warning(f"Outside market hours: {now}")
        return within

    # ── Position sizing ───────────────────────────────────────────────────────

    def calculate_quantity(self, entry_price: float, stop_loss: float) -> int:
        """Return share quantity so max loss per trade = max_risk_per_trade_pct of capital."""
        risk_per_share = abs(entry_price - stop_loss)
        if risk_per_share <= 0:
            logger.error("calculate_quantity: zero risk per share — check SL value")
            return 0
        max_risk = self._r["total_capital"] * self._r["max_risk_per_trade_pct"] / 100
        qty = int(max_risk / risk_per_share)
        max_pos = self._r["total_capital"] * self._r["max_position_size_pct"] / 100
        if qty * entry_price > max_pos:
            qty = int(max_pos / entry_price)
        logger.info(f"Qty={qty} | entry={entry_price} sl={stop_loss} max_risk=Rs.{max_risk:.0f}")
        return qty
