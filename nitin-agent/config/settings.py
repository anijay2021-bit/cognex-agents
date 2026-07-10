"""Nitin Agent settings — swing strategies from the Nitin R masterclass."""
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
IST = "Asia/Kolkata"

MODE = "PAPER"                      # PAPER | LIVE (live not implemented deliberately)
ACCOUNT = "Kiran - r14592"

# Fyers (reuse prajnan-agent's daily-refreshed token)
FYERS_CLIENT_ID = "FX2G3F1GB9-100"
FYERS_TOKEN_PATH = "/home/anijay2021/prajnan-agent/config/fyers_token.json"

TELEGRAM_CONFIG = BASE / "config" / "telegram_config.json"
DB_PATH = BASE / "cognex_agent.db"
LOG_DIR = BASE / "logs"
WATCHLIST = BASE / "config" / "watchlist.txt"
BENCHMARK = "NSE:NIFTY50-INDEX"

# Risk (fixed-risk model from the masterclass)
CAPITAL = 100000.0                  # paper capital
RISK_PER_TRADE_PCT = 1.0            # 1% per trade
MAX_ALLOCATION_PCT = 25.0           # max 25% capital in one stock
MAX_STOP_PCT = 8.0                  # reject setups with stop > 8% away
MAX_OPEN_POSITIONS = 3
MIN_TURNOVER_CR = 5.0

# Schedule (IST)
SCAN_TIME = "18:30"                 # daily EOD scan Mon-Fri
MONITOR_EVERY_MIN = 15              # signal/position checks during market hours
MARKET_OPEN = "09:20"
MARKET_CLOSE = "15:25"
SIGNAL_VALID_DAYS = 4               # signals expire if not triggered
