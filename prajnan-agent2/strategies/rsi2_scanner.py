"""
COGNEX Agent2 - RSI2 Strategy Scanner
Uses AngelOne SmartAPI for data — no Fyers dependency.

CE Entry: Nifty spot > 200 SMA AND RSI(2) < 5  → BUY ATM CE
CE Exit:  RSI(2) > 95 OR spot < 200 SMA
PE Entry: Nifty spot < 200 SMA AND RSI(2) > 95 → BUY ATM PE
PE Exit:  RSI(2) < 5  OR spot > 200 SMA

Timeframe: 5 minutes | 10 lots | 650 qty
"""

import time
import pandas as pd
import numpy as np
from datetime import date, timedelta, datetime
from typing import Optional
from loguru import logger
from config.settings import settings
from utils.expiry_calculator import get_expiry_dates

NIFTY_LOT_SIZE  = 65
RSI2_LOTS       = settings.rsi2_lots
RSI2_QUANTITY   = NIFTY_LOT_SIZE * RSI2_LOTS
RSI_PERIOD      = 2
SMA_PERIOD      = 200
RSI_OVERSOLD    = 5
RSI_OVERBOUGHT  = 95


class RSI2Scanner:

    def __init__(self, angelone_data=None):
        self.ao            = angelone_data
        self.active_signal = None
        self._cached_df    = None
        self._cache_bucket = None
        self._sma200_cache = None
        self._sma200_date  = None

    def update_angelone(self, angelone_data):
        self.ao = angelone_data

    def _calc_rsi2(self, series: pd.Series) -> pd.Series:
        delta = series.diff()
        gain  = delta.clip(lower=0)
        loss  = -delta.clip(upper=0)
        avg_g = gain.ewm(alpha=1/RSI_PERIOD, adjust=False).mean()
        avg_l = loss.ewm(alpha=1/RSI_PERIOD, adjust=False).mean()
        rs    = avg_g / avg_l.replace(0, np.nan)
        return (100 - (100 / (1 + rs))).fillna(50)

    def _get_sma200_daily(self) -> Optional[float]:
        today = date.today()
        if self._sma200_date == today and self._sma200_cache is not None:
            return self._sma200_cache
        if self.ao is None:
            logger.error("AngelOne data connector not set")
            return None
        df = self.ao.get_nifty_daily_candles(days=300)
        if df is None or len(df) < SMA_PERIOD:
            logger.error(f"Not enough daily candles for SMA200 (got {len(df) if df is not None else 0})")
            return None
        sma200 = df["close"].rolling(SMA_PERIOD).mean().iloc[-1]
        self._sma200_cache = round(float(sma200), 2)
        self._sma200_date  = today
        logger.info(f"SMA200 refreshed: {self._sma200_cache}")
        return self._sma200_cache

    def _get_candles_cached(self) -> Optional[pd.DataFrame]:
        now            = datetime.now()
        current_bucket = now.replace(second=0, microsecond=0)
        current_bucket = current_bucket.replace(minute=(now.minute // 5) * 5)
        if (self._cached_df is not None and
                self._cache_bucket is not None and
                self._cache_bucket >= current_bucket):
            return self._cached_df
        if self.ao is None:
            logger.error("AngelOne data connector not set")
            return None
        df = self.ao.get_nifty_5min_candles()
        if df is not None and len(df) > 0:
            self._cached_df    = df
            self._cache_bucket = current_bucket
            logger.debug(
                f"RSI2: Fresh 5-min candles fetched "
                f"at bucket {current_bucket.strftime('%H:%M')} "
                f"| rows: {len(df)}"
            )
        return self._cached_df

    def scan(self, spot_price: float = 0) -> Optional[dict]:
        try:
            sma200 = self._get_sma200_daily()
            if sma200 is None:
                logger.warning("RSI2: SMA200 unavailable — skipping scan")
                return None

            df = self._get_candles_cached()
            if df is None or len(df) < 10:
                logger.warning("RSI2: Not enough 5-min candles — skipping")
                return None

            df["rsi2"] = self._calc_rsi2(df["close"])
            latest     = df.iloc[-2]
            rsi2_val   = round(float(latest["rsi2"]), 2)
            close      = round(float(latest["close"]), 2)
            candle_time = latest["timestamp"].strftime("%H:%M") \
                          if hasattr(latest["timestamp"], "strftime") \
                          else str(latest["timestamp"])

            spot = spot_price if spot_price > 0 else close

            logger.info(
                f"RSI2 Check | Spot:{spot} "
                f"SMA200:{sma200} RSI2:{rsi2_val} Time:{candle_time}"
            )

            if self.active_signal:
                return self._check_exit(spot, sma200, rsi2_val)

            if spot > sma200 and rsi2_val < RSI_OVERSOLD:
                return self._build_signal("CE", spot, sma200, rsi2_val)

            if spot < sma200 and rsi2_val > RSI_OVERBOUGHT:
                return self._build_signal("PE", spot, sma200, rsi2_val)

            logger.debug(
                f"RSI2: No signal — RSI:{rsi2_val} "
                f"SMA:{sma200} Spot:{spot}"
            )
            return None

        except Exception as e:
            logger.error(f"RSI2 scan error: {e}")
            return None

    def _build_signal(self, direction: str,
                      spot: float, sma200: float,
                      rsi2: float) -> dict:
        expiry = get_expiry_dates()
        strike = round(spot / 50) * 50
        signal = {
            "action":    "BUY",
            "direction": direction,
            "strike":    strike,
            "expiry":    expiry.get("weekly", ""),
            "quantity":  RSI2_QUANTITY,
            "lots":      RSI2_LOTS,
            "spot":      spot,
            "sma200":    sma200,
            "rsi2":      rsi2,
            "reason":    (
                f"RSI2={rsi2} < {RSI_OVERSOLD} + Spot > SMA200"
                if direction == "CE"
                else
                f"RSI2={rsi2} > {RSI_OVERBOUGHT} + Spot < SMA200"
            )
        }
        self.active_signal = signal
        logger.info(
            f"RSI2 SIGNAL: {direction} | Strike:{strike} "
            f"| Spot:{spot} | RSI2:{rsi2}"
        )
        return signal

    def _check_exit(self, spot: float,
                    sma200: float, rsi2: float) -> Optional[dict]:
        direction = self.active_signal.get("direction")
        exit_ce   = (direction == "CE" and
                     (rsi2 > RSI_OVERBOUGHT or spot < sma200))
        exit_pe   = (direction == "PE" and
                     (rsi2 < RSI_OVERSOLD or spot > sma200))
        if exit_ce or exit_pe:
            reason = (
                f"RSI2={rsi2} > {RSI_OVERBOUGHT}"
                if rsi2 > RSI_OVERBOUGHT
                else f"Spot {spot} crossed SMA200 {sma200}"
            )
            exit_signal = {
                "action":    "EXIT",
                "direction": direction,
                "quantity":  RSI2_QUANTITY,
                "reason":    reason,
                "spot":      spot,
                "rsi2":      rsi2,
            }
            logger.info(f"RSI2 EXIT: {direction} | {reason}")
            self.active_signal = None
            return exit_signal
        return None

    def should_exit(self, pos: dict, spot: float):
        """Return an exit-reason string if this open position should close, else None.
        Called by order_executor.monitor_positions() every minute (C4 fix)."""
        try:
            opt = (pos.get("option_type") or pos.get("direction") or "").upper()
            if opt not in ("CE", "PE"):
                return None
            sma200 = self._get_sma200_daily()
            if sma200 is None:
                return None
            df = self._get_candles_cached()
            if df is None or len(df) < 10:
                return None
            df = df.copy()
            df["rsi2"] = self._calc_rsi2(df["close"])
            rsi2_val = round(float(df.iloc[-2]["rsi2"]), 2)
            if opt == "CE" and (rsi2_val > RSI_OVERBOUGHT or spot < sma200):
                return (f"RSI2={rsi2_val}>{RSI_OVERBOUGHT}"
                        if rsi2_val > RSI_OVERBOUGHT else f"Spot {spot}<SMA200 {sma200}")
            if opt == "PE" and (rsi2_val < RSI_OVERSOLD or spot > sma200):
                return (f"RSI2={rsi2_val}<{RSI_OVERSOLD}"
                        if rsi2_val < RSI_OVERSOLD else f"Spot {spot}>SMA200 {sma200}")
            return None
        except Exception as e:
            logger.error(f"should_exit error: {e}")
            return None

    def reset(self):
        self.active_signal = None
        self._cached_df    = None
        self._cache_bucket = None

rsi2_scanner = RSI2Scanner()
