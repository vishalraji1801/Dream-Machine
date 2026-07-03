"""
Paper trading simulator.
Drop-in replacement for OrderExecutor — same interface, no real orders placed.
Controlled by paper_trading.enabled in config.yaml.
"""
from typing import Optional

from src.data_fetcher import DataFetcher
from src.logger import get_logger

logger = get_logger("paper_trader")


class PaperTrader:
    """
    Simulates order fills at current market price.
    LIMIT fills at the limit price; MARKET fills at live LTP.
    A configurable slippage percentage is applied for realism:
    BUY fills slightly higher, SELL fills slightly lower.
    GTT OCO orders are tracked as integers and cancelled as no-ops.
    """

    def __init__(self, fetcher: DataFetcher, cfg: dict):
        self._fetcher = fetcher
        self._exchange = cfg["trading"]["exchange"]
        self._slippage = cfg.get("paper_trading", {}).get("simulated_slippage_pct", 0.05) / 100
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
        """Simulate an order fill instantly at price ± slippage."""
        fill_price = self._fill_price(symbol, direction, price, order_type)
        self._order_seq += 1
        order_id = f"PAPER-{self._order_seq:06d}"
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
        """Return the pre-recorded COMPLETE result immediately."""
        return self._orders.get(order_id)

    def cancel_order(self, order_id: str) -> bool:
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

    def _fill_price(self, symbol: str, direction: str, price: float, order_type: str) -> float:
        """Determine simulated fill price with slippage."""
        if order_type == "MARKET":
            quotes = self._fetcher.get_quotes([symbol])
            if quotes and symbol in quotes:
                price = quotes[symbol]["ltp"]

        if direction == "BUY":
            return round(price * (1 + self._slippage), 2)
        return round(price * (1 - self._slippage), 2)
