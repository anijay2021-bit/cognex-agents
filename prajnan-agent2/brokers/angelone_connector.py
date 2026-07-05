import time
from loguru import logger

try:
    from SmartApi import SmartConnect
    import pyotp
    ANGELONE_AVAILABLE = True
except ImportError:
    ANGELONE_AVAILABLE = False

from config.settings import settings


class AngelOneConnector:

    def __init__(self):
        self.api         = None
        self._connected  = False
        self.auth_token  = None

    def connect(self) -> bool:
        if not ANGELONE_AVAILABLE:
            logger.error("smartapi-python not installed")
            return False
        try:
            self.api = SmartConnect(api_key=settings.angelone_api_key)
            totp = pyotp.TOTP(settings.angelone_totp_secret).now()
            data = self.api.generateSession(
                clientCode = settings.angelone_client_id,
                password   = settings.angelone_password,
                totp       = totp
            )
            if data.get("status"):
                self.auth_token = data["data"]["jwtToken"]
                self._connected = True
                logger.success(f"AngelOne connected: {data['data'].get('name','')}")
                return True
            else:
                logger.error(f"AngelOne login failed: {data}")
                return False
        except Exception as e:
            logger.error(f"AngelOne connect error: {e}")
            return False

    def place_order(self, symbol: str, token: str, qty: int,
                    side: str, order_type: str = "MARKET",
                    price: float = 0, product: str = "INTRADAY") -> dict:
        """
        Place order on AngelOne.
        side: BUY or SELL
        order_type: MARKET or LIMIT
        product: INTRADAY or CARRYFORWARD
        """
        if not self._connected:
            logger.error("AngelOne not connected")
            return {"status": False, "message": "Not connected"}

        if settings.is_paper_mode:
            logger.info(f"PAPER MODE — simulating {side} {qty} {symbol} @ {price}")
            return {
                "status":    True,
                "orderid":   f"PAPER_{int(time.time())}",
                "message":   "Paper trade simulated",
                "paper_mode": True
            }

        try:
            order_params = {
                "variety":         "NORMAL",
                "tradingsymbol":   symbol,
                "symboltoken":     token,
                "transactiontype": side,
                "exchange":        "NFO",
                "ordertype":       order_type,
                "producttype":     product,
                "duration":        "DAY",
                "price":           str(price) if order_type == "LIMIT" else "0",
                "quantity":        str(qty),
                "squareoff":       "0",
                "stoploss":        "0",
            }
            response = self.api.placeOrder(order_params)
            logger.info(f"Order placed: {response}")
            return {"status": True, "orderid": response, "message": "Order placed"}
        except Exception as e:
            logger.error(f"Order placement error: {e}")
            return {"status": False, "message": str(e)}

    def get_positions(self) -> list:
        if not self._connected:
            return []
        try:
            data = self.api.position()
            if data.get("status"):
                return data.get("data") or []
            return []
        except Exception as e:
            logger.error(f"Positions error: {e}")
            return []

    def get_ltp(self, exchange: str, symbol: str, token: str) -> float:
        if not self._connected:
            return 0.0
        try:
            data = self.api.ltpData(exchange, symbol, token)
            if data.get("status"):
                return float(data["data"].get("ltp", 0))
            return 0.0
        except Exception as e:
            logger.error(f"LTP error: {e}")
            return 0.0

    def cancel_order(self, order_id: str, variety: str = "NORMAL") -> bool:
        if not self._connected:
            return False
        try:
            data = self.api.cancelOrder(order_id, variety)
            return data.get("status", False)
        except Exception as e:
            logger.error(f"Cancel order error: {e}")
            return False


angelone_connector = AngelOneConnector()
