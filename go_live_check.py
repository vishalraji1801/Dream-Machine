"""
Go-live readiness CLI (V2 P7). Reads paper trades from logs/trades.db and reports
whether the paper evidence meets objective criteria. Does NOT flip any flag.

Usage: python go_live_check.py
"""
import os

import yaml

from src.go_live import evaluate_readiness, format_report
from src.logger import get_logger, setup_logging
from src.trade_db import TradeDB

logger = get_logger("go_live_check")


def main() -> None:
    with open(os.path.join("config", "config.yaml")) as f:
        cfg = yaml.safe_load(f)
    setup_logging(level=cfg["logging"]["level"], retention_days=cfg["logging"]["retention_days"])

    db = TradeDB()
    paper = db.trades(source="paper")
    if not paper:
        print("No paper trades recorded yet. Run the bot in paper mode first.")
        return

    criteria = cfg.get("go_live", {})
    report = evaluate_readiness(paper, criteria)
    print(format_report(report))


if __name__ == "__main__":
    main()
