"""
Paper trading simulator.
Drop-in replacement for OrderExecutor — same interface, no real orders placed.
Controlled by paper_trading.enabled in config.yaml.

Fill modes:
- Default (realistic_fills: false): every order fills instantly at
  price ± slippage — optimistic, useful for pipeline testing.
- Realistic (realistic_fills: true): LIMIT orders fill only if the live LTP
  has crossed the limit price (BUY: LTP <= limit, SELL: LTP >= limit);
  otherwise the order stays OPEN and can be cancelled. MARKET always fills.
"""
from typing import Optional

from src.data_fetcher import DataFetcher
from src.logger import get_logger

logger = get_logger("paper_trader")


class PaperTrader:
    """
    Simulates order fills at current market price.
    A configurable slippage percentage is applied for realism:
    BUY fills slightly higher, SELL fills slightly lower.
    GTT OCO orders are tracked as integers and cancelled as no-ops.
    """

    def __init__(self, fetcher: DataFetcher, cfg: dict):
        self._fetcher = fetcher
        self._exchange = cfg["trading"]["exchange"]
        pt_cfg = cfg.get("paper_trading", {})
        self._slippage = pt_cfg.get("simulated_slippage_pct", 0.05) / 100
        self._realistic = pt_cfg.get("realistic_fills", False)
        self._orders: dict[str, dict] = {}
        self._order_seq = 0
        self._gtt_seq = 0

    # ── Orders ────────────────────────────────────────────────────────────────

    def place_order(
        self,
        symbol: str,
        direction: str,
        quantity: int,
        price: float,
        order_type: str = "LIMIT",
    ) -> Optional[str]:
        """Simulate an order. Fills instantly unless realistic mode leaves it OPEN."""
        self._order_seq += 1
        order_id = f"PAPER-{self._order_seq:06d}"

        ltp = self._get_ltp(symbol)

        if self._realistic and order_type == "LIMIT" and ltp is not None \
                and not self._limit_fillable(direction, price, ltp):
            self._orders[order_id] = {
                "status":           "OPEN",
                "average_price":    0.0,
                "filled_quantity":  0,
                "pending_quantity": quantity,
                "status_message":   f"limit {price} not crossed (LTP {ltp})",
                "order_id":         order_id,
            }
            logger.info(
                f"[PAPER] {direction} {quantity}x{symbol} LIMIT {price} — "
                f"OPEN, LTP {ltp} has not crossed — {order_id}"
            )
            return order_id

        fill_price = self._fill_price(direction, price, order_type, ltp)
        self._orders[order_id] = {
            "status":           "COMPLETE",
            "average_price":    fill_price,
            "filled_quantity":  quantity,
            "pending_quantity": 0,
            "status_message":   None,
            "order_id":         order_id,
        }
        logger.info(
            f"[PAPER] {direction} {quantity}x{symbol} @ {fill_price} "
            f"({order_type}) — {order_id}"
        )
        return order_id

    def monitor_order(self, order_id: str, timeout_sec: int = 60) -> Optional[dict]:
        """Return the pre-recorded result immediately."""
        return self._orders.get(order_id)

    def cancel_order(self, order_id: str) -> bool:
        order = self._orders.get(order_id)
        if order and order["status"] == "OPEN":
            order["status"] = "CANCELLED"
            order["pending_quantity"] = 0
            logger.info(f"[PAPER] cancel_order {order_id} — cancelled")
        else:
            logger.info(f"[PAPER] cancel_order {order_id} — no-op")
        return True

    def get_order_status(self, order_id: str) -> Optional[dict]:
        return self._orders.get(order_id)

    # ── GTT ───────────────────────────────────────────────────────────────────

    def place_gtt_oco(
        self,
        symbol: str,
        direction: str,
        quantity: int,
        stop_loss: float,
        target: float,
        last_price: float,
    ) -> Optional[int]:
        """Register a simulated GTT and return a fake trigger_id."""
        self._gtt_seq += 1
        logger.info(
            f"[PAPER] GTT OCO registered: {symbol} SL={stop_loss} "
            f"target={target} gtt_id={self._gtt_seq}"
        )
        return self._gtt_seq

    def cancel_gtt(self, gtt_id: int) -> bool:
        logger.info(f"[PAPER] cancel_gtt gtt_id={gtt_id} — no-op")
        return True

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _limit_fillable(direction: str, limit_price: float, ltp: float) -> bool:
        """A BUY LIMIT fills when LTP <= limit; a SELL LIMIT when LTP >= limit."""
        if direction == "BUY":
            return ltp <= limit_price
        return ltp >= limit_price

    def _get_ltp(self, symbol: str) -> Optional[float]:
        quotes = self._fetcher.get_quotes([symbol])
        if quotes and symbol in quotes:
            return quotes[symbol]["ltp"]
        return None

    def _fill_price(self, direction: str, price: float, order_type: str,
                    ltp: Optional[float]) -> float:
        """Determine simulated fill price with slippage."""
        if order_type == "MARKET" and ltp is not None:
            price = ltp

        if direction == "BUY":
            return round(price * (1 + self._slippage), 2)
        return round(price * (1 - self._slippage), 2)
