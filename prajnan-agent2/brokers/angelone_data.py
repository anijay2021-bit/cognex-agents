"""
AngelOne Data Connector for cognex-agent2
Replaces Fyers completely — fetches candles and spot price
using father's AngelOne SmartAPI credentials only.
"""
import time
import pandas as pd
import numpy as np
from datetime import datetime, date, timedelta
from typing import Optional
from loguru import logger

try:
    from SmartApi import SmartConnect
    import pyotp
    ANGELONE_AVAILABLE = True
except ImportError:
    ANGELONE_AVAILABLE = False

from config.settings import settings

NIFTY_SYMBOL   = "Nifty 50"
NIFTY_TOKEN    = "99926000"
NIFTY_EXCHANGE = "NSE"
INDIAVIX_TOKEN = "99919003"

class AngelOneDataConnector:

    def __init__(self):
        self.api         = None
        self._connected  = False
        self.auth_token  = None
        self._last_login = None

    def connect(self) -> bool:
        if not ANGELONE_AVAILABLE:
            logger.error("smartapi-python not installed")
            return False
        try:
            self.api  = SmartConnect(api_key=settings.angelone_api_key)
            totp      = pyotp.TOTP(settings.angelone_totp_secret).now()
            data      = self.api.generateSession(
                clientCode = settings.angelone_client_id,
                password   = settings.angelone_password,
                totp       = totp
            )
            if data.get("status"):
                self.auth_token  = data["data"]["jwtToken"]
                self._connected  = True
                self._last_login = datetime.now()
                logger.success(
                    f"AngelOne data connected: "
                    f"{data['data'].get('name', settings.angelone_client_id)}"
                )
                return True
            else:
                logger.error(f"AngelOne data login failed: {data}")
                return False
        except Exception as e:
            logger.error(f"AngelOne data connect error: {e}")
            return False

    def _ensure_connected(self):
        if not self._connected or self._last_login is None:
            self.connect()
            return
        age = (datetime.now() - self._last_login).total_seconds() / 3600
        if age > 6:
            logger.info("AngelOne session refreshing...")
            self.connect()

    def get_candles(self, token: str, interval: str,
                    from_date: str, to_date: str,
                    exchange: str = "NSE") -> Optional[pd.DataFrame]:
        self._ensure_connected()
        try:
            params = {
                "exchange":    exchange,
                "symboltoken": token,
                "interval":    interval,
                "fromdate":    from_date,
                "todate":      to_date
            }
            resp = self.api.getCandleData(params)
            if not resp.get("status"):
                logger.error(f"getCandleData failed: {resp.get('message')}")
                return None
            candles = resp.get("data", [])
            if not candles:
                logger.warning("No candle data returned")
                return None
            df = pd.DataFrame(
                candles,
                columns=["timestamp","open","high","low","close","volume"]
            )
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            df = df.sort_values("timestamp").reset_index(drop=True)
            df[["open","high","low","close","volume"]] = \
                df[["open","high","low","close","volume"]].apply(pd.to_numeric)
            return df
        except Exception as e:
            logger.error(f"get_candles error: {e}")
            return None

    def get_nifty_5min_candles(self) -> Optional[pd.DataFrame]:
        time.sleep(5)  # rate limit protection
        today   = datetime.now()
        from_dt = (today - timedelta(days=60)).strftime("%Y-%m-%d 09:00")
        to_dt   = today.strftime("%Y-%m-%d %H:%M")
        return self.get_candles(
            token     = NIFTY_TOKEN,
            interval  = "FIVE_MINUTE",
            from_date = from_dt,
            to_date   = to_dt,
            exchange  = "NSE"
        )

    def get_nifty_daily_candles(self, days: int = 300) -> Optional[pd.DataFrame]:
        time.sleep(5)  # rate limit protection
        today   = datetime.now()
        from_dt = (today - timedelta(days=days)).strftime("%Y-%m-%d 09:00")
        to_dt   = today.strftime("%Y-%m-%d %H:%M")
        return self.get_candles(
            token     = NIFTY_TOKEN,
            interval  = "ONE_DAY",
            from_date = from_dt,
            to_date   = to_dt,
            exchange  = "NSE"
        )

    def get_nifty_spot(self) -> float:
        self._ensure_connected()
        try:
            data = self.api.ltpData(NIFTY_EXCHANGE, NIFTY_SYMBOL, NIFTY_TOKEN)
            if data.get("status"):
                return float(data["data"].get("ltp", 0))
            logger.error(f"Nifty LTP failed: {data.get('message')}")
            return 0.0
        except Exception as e:
            logger.error(f"get_nifty_spot error: {e}")
            return 0.0

    def get_vix(self) -> float:
        self._ensure_connected()
        try:
            return 15.0  # VIX token unsupported — using default
            if data.get("status"):
                return float(data["data"].get("ltp", 0))
            return 0.0
        except Exception as e:
            logger.error(f"get_vix error: {e}")
            return 0.0

    def get_full_market_snapshot(self) -> dict:
        nifty = self.get_nifty_spot()
        vix   = self.get_vix()
        return {
            "nifty_spot": nifty,
            "vix":        vix,
            "banknifty":  0.0,
            "pcr":        0.0,
        }

angelone_data = AngelOneDataConnector()
