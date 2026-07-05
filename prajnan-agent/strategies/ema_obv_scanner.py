"""
COGNEX Agent - EMA Crossover + OBV Strategy Scanner
Trend momentum strategy using Nifty Futures for signals,
trades ATM CE/PE options.

Entry rules (ALL must be true):
  - 9 EMA crosses above 21 EMA on 15-min Nifty Futures chart (bullish)
  - OBV making higher highs (volume accumulating)
  - Time filter: after 9:30 AM IST (avoid open noise)

Exit:
  - Target: 1.5x premium paid
  - Stop: 9 EMA crosses back below 21 EMA OR 30% premium loss

Instrument: Nifty Futures (front month) for signals
Trade: ATM CE options (10 lots, 650 qty)
Timeframe: 15 minutes
"""

import pandas as pd
import numpy as np
from datetime import date, timedelta, datetime
from typing import Optional
from loguru import logger
from config.settings import settings
from utils.expiry_calculator import get_monthly_expiry, get_expiry_dates

NIFTY_LOT_SIZE   = 65
EMA_LOTS         = 10
EMA_QUANTITY     = NIFTY_LOT_SIZE * EMA_LOTS   # 650
EMA_FAST         = 9
EMA_SLOW         = 21
TARGET_MULT      = 1.5   # 1.5x premium
STOP_PCT         = 0.30  # 30% premium loss


def _get_nifty_futures_symbol() -> str:
    """
    Build front-month Nifty Futures symbol for Fyers.
    Format: NSE:NIFTYYYMMMFUT
    Example: NSE:NIFTY26JUNFUT
    Rolls to next month if today is expiry day after 3:30 PM.
    """
    today    = date.today()
    expiry   = get_monthly_expiry(today)
    now      = datetime.now()
    ist_hour = now.hour + 5 + (1 if now.minute >= 30 else 0)

    # Roll to next month if today is expiry and market closed
    if today == expiry and ist_hour >= 15:
        next_month = today.replace(day=1) + timedelta(days=32)
        expiry     = get_monthly_expiry(next_month.replace(day=1))

    month_str = expiry.strftime("%b").upper()   # JAN, FEB ... DEC
    year_str  = expiry.strftime("%y")           # 26, 27 ...
    symbol    = f"NSE:NIFTY{year_str}{month_str}FUT"
    logger.debug(f"Nifty Futures symbol: {symbol} (expiry: {expiry})")
    return symbol


class EmaObvScanner:

    def __init__(self, fyers_model=None):
        self.fyers          = fyers_model
        self.active_signal  = None
        self._cached_df     = None
        self._cache_bucket  = None
        self._entry_premium = None   # tracks premium at entry for exit logic

    def update_fyers(self, fyers_model):
        self.fyers = fyers_model

    def _calc_ema(self, series: pd.Series, period: int) -> pd.Series:
        return series.ewm(span=period, adjust=False).mean()


    def _calc_obv(self, df: pd.DataFrame) -> pd.Series:
        """On Balance Volume calculation"""
        obv    = [0]
        closes = df["close"].values
        vols   = df["volume"].values
        for i in range(1, len(df)):
            if closes[i] > closes[i-1]:
                obv.append(obv[-1] + vols[i])
            elif closes[i] < closes[i-1]:
                obv.append(obv[-1] - vols[i])
            else:
                obv.append(obv[-1])
        return pd.Series(obv, index=df.index)

    def _obv_higher_highs(self, obv: pd.Series, lookback: int = 5) -> bool:
        """
        Check if OBV is making higher highs over last N candles.
        True = volume is accumulating = bullish confirmation.
        """
        if len(obv) < lookback + 1:
            return False
        recent = obv.iloc[-(lookback+1):]
        # Check if OBV trend is rising — slope positive
        x   = np.arange(len(recent))
        y   = recent.values.astype(float)
        slope = np.polyfit(x, y, 1)[0]
        return slope > 0

    def _fetch_futures_candles(self) -> Optional[pd.DataFrame]:
        """Fetch 15-min candles from Nifty Futures via Fyers"""
        if self.fyers is None:
            logger.error("EMA+OBV: Fyers model not set")
            return None
        try:
            symbol    = _get_nifty_futures_symbol()
            today     = date.today()
            from_date = (today - timedelta(days=60)).strftime("%Y-%m-%d")
            to_date   = today.strftime("%Y-%m-%d")
            data = {
                "symbol":      symbol,
                "resolution":  "15",
                "date_format": "1",
                "range_from":  from_date,
                "range_to":    to_date,
                "cont_flag":   "1"
            }
            response = self.fyers.history(data=data)
            if response.get("s") != "ok":
                logger.error(f"EMA+OBV futures fetch failed: {response.get('message')}")
                return None
            candles = response.get("candles", [])
            if not candles:
                logger.warning("EMA+OBV: No futures candles returned")
                return None
            df = pd.DataFrame(
                candles,
                columns=["timestamp","open","high","low","close","volume"]
            )
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
            df = df.sort_values("timestamp").reset_index(drop=True)
            df[["open","high","low","close","volume"]] = \
                df[["open","high","low","close","volume"]].apply(pd.to_numeric)
            logger.debug(f"EMA+OBV: Fetched {len(df)} 15-min futures candles")
            return df
        except Exception as e:
            logger.error(f"EMA+OBV fetch error: {e}")
            return None

    def _get_candles_cached(self) -> Optional[pd.DataFrame]:
        """Cache candles per 15-min boundary"""
        now            = datetime.now()
        current_bucket = now.replace(second=0, microsecond=0)
        current_bucket = current_bucket.replace(
            minute=(now.minute // 15) * 15
        )
        if (self._cached_df is not None and
                self._cache_bucket is not None and
                self._cache_bucket >= current_bucket):
            return self._cached_df
        df = self._fetch_futures_candles()
        if df is not None and len(df) > 0:
            self._cached_df    = df
            self._cache_bucket = current_bucket
            logger.debug(
                f"EMA+OBV: Fresh 15-min candles at "
                f"bucket {current_bucket.strftime('%H:%M')}"
            )
        return self._cached_df

    def _is_after_930(self) -> bool:
        """Time filter — avoid first 15 min of market open"""
        now      = datetime.now()
        ist_hour = now.hour + 5
        ist_min  = now.minute + 30
        if ist_min >= 60:
            ist_hour += 1
            ist_min  -= 60
        return ist_hour > 9 or (ist_hour == 9 and ist_min >= 30)

    def scan(self, spot_price: float = 0) -> Optional[dict]:
        """Main scan — returns signal dict or None"""
        try:
            # Time filter
            if not self._is_after_930():
                logger.debug("EMA+OBV: Before 9:30 IST — skipping")
                return None

            df = self._get_candles_cached()
            if df is None or len(df) < EMA_SLOW + 5:
                logger.warning("EMA+OBV: Not enough candles — skipping")
                return None

            # Calculate indicators
            df["ema9"]  = self._calc_ema(df["close"], EMA_FAST)
            df["ema21"] = self._calc_ema(df["close"], EMA_SLOW)
            df["obv"]   = self._calc_obv(df)

            curr         = df.iloc[-1]
            prev         = df.iloc[-2]
            ema9_curr    = round(float(curr["ema9"]), 2)
            ema21_curr   = round(float(curr["ema21"]), 2)
            ema9_prev    = round(float(prev["ema9"]), 2)
            ema21_prev   = round(float(prev["ema21"]), 2)
            candle_time  = curr["timestamp"].strftime("%H:%M")

            logger.info(
                f"EMA+OBV | EMA9:{ema9_curr} EMA21:{ema21_curr} "
            )

            # Exit check if position open
            if self.active_signal:
                return self._check_exit(
                    df, ema9_curr, ema21_curr,
                    ema9_prev, ema21_prev
                )

            # Bullish cross: EMA9 crosses above EMA21
            bullish_cross = (ema9_prev <= ema21_prev and
                             ema9_curr > ema21_curr)

            if not bullish_cross:
                logger.debug(
                    f"EMA+OBV: No cross — "
                    f"EMA9:{ema9_curr} EMA21:{ema21_curr}"
                )
                return None


            # OBV higher highs — volume confirming
            obv_bullish = self._obv_higher_highs(df["obv"], lookback=5)
            if not obv_bullish:
                logger.debug("EMA+OBV: OBV not making higher highs — skipping")
                return None

            # All conditions met — build signal
            return self._build_signal(
                spot_price or float(curr["close"]),
                ema9_curr, ema21_curr
            )

        except Exception as e:
            logger.error(f"EMA+OBV scan error: {e}")
            return None

    def _build_signal(self, spot: float,
                      ema9: float, ema21: float) -> dict:
        expiry = get_expiry_dates()
        strike = round(spot / 50) * 50   # ATM strike
        signal = {
            "action":        "BUY",
            "strategy":      "EMA_OBV",
            "direction":     "CE",
            "strike":        strike,
            "expiry":        expiry.get("weekly", ""),
            "quantity":      EMA_QUANTITY,
            "lots":          EMA_LOTS,
            "spot":          spot,
            "ema9":          ema9,
            "ema21":         ema21,
            "target_mult":   TARGET_MULT,
            "stop_pct":      STOP_PCT,
            "reason":        (
                f"EMA9({ema9}) crossed above EMA21({ema21}) | "
                f"OBV bullish"
            )
        }
        self.active_signal = signal
        logger.info(
            f"EMA+OBV SIGNAL: CE | Strike:{strike} "
            f"| Spot:{spot} | EMA9:{ema9} > EMA21:{ema21}"
        )
        return signal

    def _check_exit(self, df: pd.DataFrame,
                    ema9_curr: float, ema21_curr: float,
                    ema9_prev: float, ema21_prev: float) -> Optional[dict]:
        """
        Exit when:
        1. EMA9 crosses back below EMA21 (trend reversal)
        2. Premium dropped 30% (handled in main.py via LTP check)
        """
        bearish_cross = (ema9_prev >= ema21_prev and
                         ema9_curr < ema21_curr)
        if bearish_cross:
            exit_signal = {
                "action":    "EXIT",
                "strategy":  "EMA_OBV",
                "direction": self.active_signal.get("direction"),
                "quantity":  EMA_QUANTITY,
                "reason":    (
                    f"EMA9({ema9_curr}) crossed below "
                    f"EMA21({ema21_curr}) — trend reversed"
                )
            }
            logger.info(
                f"EMA+OBV EXIT: EMA cross down | "
                f"EMA9:{ema9_curr} < EMA21:{ema21_curr}"
            )
            self.active_signal  = None
            self._entry_premium = None
            return exit_signal
        return None

    def reset(self):
        self.active_signal  = None
        self._cached_df     = None
        self._cache_bucket  = None
        self._entry_premium = None


ema_obv_scanner = EmaObvScanner()
