from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
IST  = "Asia/Kolkata"

MODE    = "PAPER"                      # PAPER | LIVE (live not implemented deliberately)
ACCOUNT = "Kiran - r14592"

FYERS_CLIENT_ID  = "FX2G3F1GB9-100"
FYERS_TOKEN_PATH = "/home/anijay2021/prajnan-agent/config/fyers_token.json"

TELEGRAM_CONFIG = BASE / "config" / "telegram_config.json"
DB_PATH         = BASE / "cognex_agent.db"
LOG_DIR         = BASE / "logs"

# ---- Strategy: 18 SMA + 2-candle breakout (dashboard-controlled) ----
TIMEFRAME    = 5         # minutes: 1,3,5,10,15,30,60 - same timeframe drives both SMA and candles
SMA_PERIOD   = 18

SL_POINTS    = 15.0      # stop loss, in points of option price
TARGET_MODE  = "RR"      # "RR" | "POINTS" | "PERCENT"
TARGET_VALUE = 2.0       # meaning depends on TARGET_MODE

DAILY_LOSS_LIMIT = 20000.0

# ---- Instruments (dashboard-controlled per-instrument lots/lot size) ----
NIFTY_INDEX      = "NSE:NIFTY50-INDEX"
NIFTY_LOTS       = 1
NIFTY_LOT_SIZE   = 65

BANKNIFTY_INDEX      = "NSE:NIFTYBANK-INDEX"
BANKNIFTY_LOTS       = 1
BANKNIFTY_LOT_SIZE   = 30

SENSEX_INDEX      = "BSE:SENSEX-INDEX"
SENSEX_LOTS       = 1
SENSEX_LOT_SIZE   = 20

# ---- Schedule (IST) ----
MARKET_OPEN    = "09:20"
MARKET_CLOSE   = "15:25"
SCAN_EVERY_SEC = 30
