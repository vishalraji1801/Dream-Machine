"""
Pre-market universe builder CLI (V2 P3). Run ~08:45 before the bot starts.
Writes data_cache/universe_YYYY-MM-DD.csv. Requires a valid Kite session.

Usage: python build_universe.py
"""
import os

import yaml
from dotenv import load_dotenv

from src.auth import load_kite_session
from src.logger import get_logger, setup_logging
from src.universe_builder import UniverseBuilder

logger = get_logger("build_universe")


def main() -> None:
    load_dotenv(dotenv_path=os.path.join("config", ".env"))
    with open(os.path.join("config", "config.yaml")) as f:
        cfg = yaml.safe_load(f)
    setup_logging(level=cfg["logging"]["level"], retention_days=cfg["logging"]["retention_days"])

    kite = load_kite_session()
    universe = UniverseBuilder(cfg).build(kite)
    print(f"Universe built: {len(universe)} symbols -> data_cache/universe_"
          f"{__import__('datetime').datetime.now():%Y-%m-%d}.csv")


if __name__ == "__main__":
    main()
