"""
Transaction cost model — Zerodha intraday equity (MIS) charges.
All rates configurable under `costs:` in config.yaml; defaults match
Zerodha's published schedule for NSE intraday equity.

Components per round trip (one buy + one sell):
- Brokerage: 0.03% of each leg's value, capped at Rs.20 per executed order
- STT: 0.025% on the sell leg
- Exchange transaction charge (NSE): 0.00297% on total turnover
- SEBI charges: 0.0001% on total turnover
- Stamp duty: 0.003% on the buy leg
- GST: 18% on (brokerage + exchange txn + SEBI)
"""
from src.logger import get_logger

logger = get_logger("costs")

_DEFAULTS = {
    "enabled": True,
    "brokerage_pct": 0.03,
    "brokerage_cap": 20.0,
    "stt_sell_pct": 0.025,
    "exchange_txn_pct": 0.00297,
    "sebi_pct": 0.0001,
    "stamp_buy_pct": 0.003,
    "gst_pct": 18.0,
}


def estimate_intraday_costs(buy_value: float, sell_value: float, cfg: dict) -> float:
    """
    Estimated total charges for one intraday round trip.
    buy_value / sell_value: rupee value of each leg (price × quantity).
    cfg: full config dict (reads the `costs` section, defaults if absent).
    Returns 0.0 when costs are disabled.
    """
    c = {**_DEFAULTS, **cfg.get("costs", {})}
    if not c["enabled"]:
        return 0.0

    turnover = buy_value + sell_value

    brokerage = (
        min(buy_value * c["brokerage_pct"] / 100, c["brokerage_cap"])
        + min(sell_value * c["brokerage_pct"] / 100, c["brokerage_cap"])
    )
    stt = sell_value * c["stt_sell_pct"] / 100
    exchange = turnover * c["exchange_txn_pct"] / 100
    sebi = turnover * c["sebi_pct"] / 100
    stamp = buy_value * c["stamp_buy_pct"] / 100
    gst = (brokerage + exchange + sebi) * c["gst_pct"] / 100

    total = round(brokerage + stt + exchange + sebi + stamp + gst, 2)
    return total


def trade_leg_values(direction: str, entry_price: float, exit_price: float,
                     quantity: int) -> tuple[float, float]:
    """
    Map a trade to (buy_value, sell_value).
    A BUY trade buys at entry and sells at exit; a SELL trade is the reverse.
    """
    if direction == "BUY":
        return entry_price * quantity, exit_price * quantity
    return exit_price * quantity, entry_price * quantity
