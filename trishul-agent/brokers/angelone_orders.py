import pyotp
from SmartApi import SmartConnect
import sys
sys.path.insert(0, '/root/trishul-agent')
from config.settings import (ANGELONE_API_KEY, ANGELONE_CLIENT_ID,
                              ANGELONE_PASSWORD, ANGELONE_TOTP_SECRET, TRADING_MODE)

def get_angel_client():
    obj   = SmartConnect(api_key=ANGELONE_API_KEY)
    totp  = pyotp.TOTP(ANGELONE_TOTP_SECRET).now()
    data  = obj.generateSession(ANGELONE_CLIENT_ID, ANGELONE_PASSWORD, totp)
    if data['status']:
        return obj
    raise Exception(f"AngelOne login failed: {data}")

def place_options_order(symbol, qty, transaction_type="BUY"):
    """
    symbol: full trading symbol e.g. NIFTY2362422600CE
    qty: number of units
    transaction_type: BUY or SELL
    """
    if TRADING_MODE == "PAPER":
        print(f"[PAPER] {transaction_type} {qty} x {symbol}")
        return {"status": True, "data": {"orderid": "PAPER_ORDER"}}

    obj = get_angel_client()
    order = {
        "variety":          "NORMAL",
        "tradingsymbol":    symbol,
        "symboltoken":      "",        # AngelOne requires token - fetch via searchScrip
        "transactiontype":  transaction_type,
        "exchange":         "NFO",
        "ordertype":        "MARKET",
        "producttype":      "INTRADAY",
        "duration":         "DAY",
        "quantity":         str(qty),
    }
    response = obj.placeOrder(order)
    return response
