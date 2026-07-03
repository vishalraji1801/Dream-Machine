"""
Order executor.
Places, monitors, and cancels Kite intraday orders (FR-17 through FR-21).
"""
import time
from typing import Optional

from kiteconnect import KiteConnect
from kiteconnect import exceptions as kite_exc

from src.logger import get_logger

logger = get_logger("order_executor")

_TERMINAL_STATUSES = {"COMPLETE", "REJECTED", "CANCELLED"}
_VARIETY = "regular"
_POLL_INTERVAL = 2  # seconds between order-status polls


class OrderExecutor:
    def __init__(self, kite: KiteConnect, cfg: dict):
        self._kite = kite
        self._exchange = cfg["trading"]["exchange"]
        self._product = cfg["trading"]["product_type"]  # MIS

    # ── Place ─────────────────────────────────────────────────────────────────

    def place_order(
        self,
        symbol: str,
        direction: str,
        quantity: int,
        price: float,
        order_type: str = "LIMIT",
    ) -> Optional[str]:
        """
        Place a single-leg intraday order (FR-17).
        Returns the Kite order_id string on success, None on failure.
        direction: "BUY" or "SELL"
        order_type: "LIMIT" or "MARKET"
        """
        try:
            order_id = self._kite.place_order(
                variety=_VARIETY,
                exchange=self._exchange,
                tradingsymbol=symbol,
                transaction_type=direction,
                quantity=quantity,
                price=price if order_type == "LIMIT" else 0,
                product=self._product,
                order_type=order_type,
            )
            logger.info(
                f"Order placed: {direction} {quantity}x{symbol} @ {price} "
                f"({order_type}) — order_id={order_id}"
            )
            return str(order_id)
        except (kite_exc.InputException, kite_exc.OrderException) as exc:
            logger.error(f"Order rejected by Kite ({symbol}): {exc}")
            return None
        except Exception as exc:
            logger.error(f"place_order failed ({symbol}): {exc}")
            return None

    # ── Monitor ───────────────────────────────────────────────────────────────

    def monitor_order(self, order_id: str, timeout_sec: int = 60) -> Optional[dict]:
        """
        Poll order status until terminal state or timeout (FR-18).
        Returns dict with keys: status, average_price, filled_quantity, status_message.
        Returns None on timeout or API error.
        """
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            status = self.get_order_status(order_id)
            if status is None:
                return None
            if status["status"] in _TERMINAL_STATUSES:
                if status["status"] == "REJECTED":
                    logger.warning(
                        f"Order REJECTED {order_id}: {status.get('status_message')}"
                    )
                elif status["status"] == "COMPLETE":
                    logger.info(
                        f"Order COMPLETE {order_id}: filled {status['filled_quantity']} "
                        f"@ avg {status['average_price']}"
                    )
                else:
                    logger.info(f"Order {status['status']} {order_id}")
                return status
            time.sleep(_POLL_INTERVAL)

        logger.warning(f"monitor_order timed out after {timeout_sec}s for {order_id}")
        return None

    # ── Cancel ────────────────────────────────────────────────────────────────

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order (FR-19). Returns True on success."""
        try:
            self._kite.cancel_order(variety=_VARIETY, order_id=order_id)
            logger.info(f"Order cancelled: {order_id}")
            return True
        except (kite_exc.InputException, kite_exc.OrderException) as exc:
            logger.error(f"cancel_order failed ({order_id}): {exc}")
            return False
        except Exception as exc:
            logger.error(f"cancel_order unexpected error ({order_id}): {exc}")
            return False

    # ── GTT OCO ───────────────────────────────────────────────────────────────

    def place_gtt_oco(
        self,
        symbol: str,
        direction: str,
        quantity: int,
        stop_loss: float,
        target: float,
        last_price: float,
    ) -> Optional[int]:
        """
        Place a GTT OCO (two-leg) order as a safety net for SL + target exits.
        If the bot crashes, Kite's servers will still close the position.
        direction: direction of the ENTRY ("BUY" or "SELL") — exit is the opposite.
        Returns gtt_id (int) on success, None on failure.
        """
        exit_txn = "SELL" if direction == "BUY" else "BUY"
        # BUY position: lower trigger = SL, upper trigger = target
        # SELL position: lower trigger = target, upper trigger = SL
        if direction == "BUY":
            trigger_values = [stop_loss, target]
        else:
            trigger_values = [target, stop_loss]

        orders = [
            {"transaction_type": exit_txn, "quantity": quantity,
             "order_type": "LIMIT", "product": self._product, "price": trigger_values[0]},
            {"transaction_type": exit_txn, "quantity": quantity,
             "order_type": "LIMIT", "product": self._product, "price": trigger_values[1]},
        ]
        try:
            result = self._kite.place_gtt(
                trigger_type="two-leg",
                tradingsymbol=symbol,
                exchange=self._exchange,
                trigger_values=trigger_values,
                last_price=last_price,
                orders=orders,
            )
            gtt_id = result.get("trigger_id")
            logger.info(f"GTT OCO placed: {symbol} | SL={stop_loss} target={target} | gtt_id={gtt_id}")
            return gtt_id
        except Exception as exc:
            logger.error(f"place_gtt_oco failed ({symbol}): {exc}")
            return None

    def cancel_gtt(self, gtt_id: int) -> bool:
        """Cancel a Kite GTT order. Returns True on success."""
        try:
            self._kite.cancel_gtt(gtt_id)
            logger.info(f"GTT cancelled: gtt_id={gtt_id}")
            return True
        except Exception as exc:
            logger.error(f"cancel_gtt failed (gtt_id={gtt_id}): {exc}")
            return False

    # ── Status query ──────────────────────────────────────────────────────────

    def get_order_status(self, order_id: str) -> Optional[dict]:
        """
        Fetch current order state from Kite (FR-21).
        Returns normalised dict or None on API error.
        """
        try:
            history = self._kite.order_history(order_id)
            if not history:
                logger.warning(f"Empty order history for {order_id}")
                return None
            latest = history[-1]
            return {
                "status":           latest.get("status", "UNKNOWN"),
                "average_price":    latest.get("average_price", 0.0),
                "filled_quantity":  latest.get("filled_quantity", 0),
                "pending_quantity": latest.get("pending_quantity", 0),
                "status_message":   latest.get("status_message"),
                "order_id":         order_id,
            }
        except Exception as exc:
            logger.error(f"get_order_status failed ({order_id}): {exc}")
            return None
