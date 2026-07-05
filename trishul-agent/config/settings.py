import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

# Fyers (same as COGNEX)
FYERS_CLIENT_ID    = os.getenv("FYERS_CLIENT_ID", "FX2G3F1GB9-100")
FYERS_SECRET_KEY   = os.getenv("FYERS_SECRET_KEY", "HG391A2HCV")
FYERS_REDIRECT_URI = os.getenv("FYERS_REDIRECT_URI", "https://trade.fyers.in/api-login/redirect-uri/index.html")

# AngelOne (same as COGNEX)
ANGELONE_API_KEY     = os.getenv("ANGELONE_API_KEY", "")
ANGELONE_CLIENT_ID   = os.getenv("ANGELONE_CLIENT_ID", "")
ANGELONE_PASSWORD    = os.getenv("ANGELONE_PASSWORD", "")
ANGELONE_TOTP_SECRET = os.getenv("ANGELONE_TOTP_SECRET", "")

# Trishul specific
TRADING_MODE       = "PAPER"
CAPITAL            = 500000
RISK_PER_TRADE_PCT = 0.01
MAX_DAILY_LOSS     = 15000
VIX_CEILING        = 16.0
MIN_DAYS_TO_EXPIRY = 3
MAX_DAYS_TO_EXPIRY = 5
NIFTY_LOT_SIZE     = 65
