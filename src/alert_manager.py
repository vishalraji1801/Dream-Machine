"""
Alert manager.
Sends real-time trade and system alerts to Telegram.
"""
import requests
from src.logger import get_logger

logger = get_logger("alert_manager")

_TEMPLATES = {
    "bot_started":        "Trading Bot ONLINE\nMarket opens in {minutes} minutes.",
    "order_placed":       "{direction} | {symbol} | Qty: {qty} | Price: {price} | Order ID: {order_id}",
    "order_filled":       "Order FILLED | {symbol} | Actual Price: {actual_price} | Slippage: {slippage}",
    "order_rejected":     "ALERT: Order REJECTED | {symbol} | Reason: {reason}",
    "sl_hit":             "SL Hit | {symbol} | Entry: {entry} | Exit: {exit_price} | Loss: Rs.{loss}",
    "target_hit":         "Target Hit | {symbol} | Entry: {entry} | Exit: {exit_price} | Profit: Rs.{profit}",
    "circuit_breaker":    "HALT: {reason}. All positions squared off.",
    "critical_error":     "ERROR: [{module}] {message}. Check logs immediately.",
    "daily_summary":      "EOD Report | Trades: {trades} | Profit: Rs.{profit} | Loss: Rs.{loss} | Net P&L: Rs.{net_pnl}",
    "signal_generated":   "Signal: {direction} {symbol} | Entry: {entry} | SL: {sl} | Target: {target}",
    "bot_stopped":        "Trading Bot OFFLINE. Reason: {reason}",
    "api_error":          "API ERROR: [{module}] {message}. Bot will retry.",
}


class AlertManager:
    def __init__(self, bot_token: str, chat_id: str):
        self._url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self._chat_id = chat_id

    def send(self, event: str, **kwargs) -> bool:
        """Send a Telegram alert for a named event. Returns True on success."""
        template = _TEMPLATES.get(event)
        if not template:
            logger.warning(f"Unknown alert event: {event}")
            return False
        try:
            message = template.format(**kwargs)
        except KeyError as exc:
            logger.error(f"Alert template missing key for '{event}': {exc}")
            return False
        return self._post(message)

    def send_raw(self, message: str) -> bool:
        """Send an arbitrary message to Telegram."""
        return self._post(message)

    def _post(self, text: str) -> bool:
        try:
            resp = requests.post(
                self._url,
                json={"chat_id": self._chat_id, "text": text},
                timeout=10,
            )
            resp.raise_for_status()
            logger.info(f"Telegram alert sent: {text[:80]}")
            return True
        except requests.RequestException as exc:
            logger.error(f"Telegram alert failed: {exc}")
            return False
