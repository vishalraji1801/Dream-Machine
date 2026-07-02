# Trading Bot V1

Autonomous intraday trading bot integrated with Zerodha's Kite Connect API.

- **Exchange:** NSE | **Instruments:** NIFTY 50 | **Timeframe:** 5-min candles
- **Strategy:** Momentum / VWAP Breakout
- **Version:** V1.0 — Rule-based only (no AI)

## Setup

```bash
# 1. Clone the repo
git clone https://github.com/vishalraji1801/trading-bot.git
cd trading-bot

# 2. Create virtual environment
python -m venv .venv
.venv\Scripts\activate      # Windows
# source .venv/bin/activate  # Mac/Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure credentials
cp config/.env.template config/.env
# Edit config/.env with your Kite API key, secret, and Telegram token

# 5. Daily login (run before market hours)
python auth.py

# 6. Start the bot
python main.py
```

## Project Structure

```
trading-bot/
  main.py                  # Scheduler & main bot loop
  auth.py                  # Daily Kite login script (run manually each morning)
  config/
    config.yaml            # All strategy, risk, and scheduler parameters
    .env.template          # Environment variable template (copy to .env)
  src/
    auth.py                # Token loader for bot startup
    data_fetcher.py        # Live quotes and candle data
    strategy.py            # Signal generation (VWAP breakout)
    risk_manager.py        # Pre-trade checks and circuit breakers
    order_executor.py      # Place, monitor, and cancel orders
    position_manager.py    # Track positions, SL/target, EOD square-off
    alert_manager.py       # Telegram notifications
    logger.py              # Structured rotating logs
  tests/                   # Pytest test suite
  logs/                    # Daily log files (gitignored)
  docs/                    # PRD and documentation
```

## Market Hours

Bot runs: **9:15 AM – 3:30 PM IST** (NSE)
EOD square-off: **3:15 PM IST**
