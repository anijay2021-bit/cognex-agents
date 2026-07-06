"""
COGNEX Agent - RSI2 Strategy Scanner
Based on Connors RSI(2) mean reversion strategy.

Logic:
CE Entry: Nifty spot > 200 SMA AND RSI(2) < 5  → BUY ATM CE
CE Exit:  RSI(2) > 95 OR spot < 200 SMA

PE Entry: Nifty spot < 200 SMA AND RSI(2) > 95 → BUY ATM PE
PE Exit:  RSI(2) < 5  OR spot > 200 SMA

Timeframe: 5 minutes
Lot size: 10 lots (650 quantity)
"""

import pandas as pd
import numpy as np
from datetime import date, timedelta, datetime
from typing import Optional
from loguru import logger
from config.settings import settings
from utils.expiry_calculator import get_expiry_dates

NIFTY_LOT_SIZE   = 65
RSI2_LOTS        = settings.rsi2_lots
RSI2_QUANTITY    = NIFTY_LOT_SIZE * RSI2_LOTS  # 650
RSI_PERIOD       = 2
SMA_PERIOD       = 200
RSI_OVERSOLD     = 5
RSI_OVERBOUGHT   = 95
TIMEFRAME        = 5          # minutes — kept for backward compatibility


class RSI2Scanner:

    def __init__(self, fyers_model=None):
        self.fyers         = fyers_model
        self.active_signal = None
        self._cached_df    = None
        self._cache_bucket = None   # tracks which 5-min bucket was last fetched

    def _get_candles_cached(self) -> Optional[pd.DataFrame]:
        """
        Fetch fresh 5-min candles only once per 5-minute boundary.
        e.g. fetches at 09:15, 09:20, 09:25 ... not every minute.
        """
        now = datetime.now()

        # Floor current time to nearest 5-min bucket
        current_bucket = now.replace(second=0, microsecond=0)
        current_bucket = current_bucket.replace(minute=(now.minute // 5) * 5)

        # Return cached data if we already fetched this bucket
        if (self._cached_df is not None and
                self._cache_bucket is not None and
                self._cache_bucket >= current_bucket):
            return self._cached_df

        # Fetch fresh candles
        df = self._fetch_nifty_candles()
        if df is not None:
            self._cached_df    = df
            self._cache_bucket = current_bucket
            logger.debug(f"RSI2: Fresh 5-min candles fetched at bucket {current_bucket.strftime('%H:%M')}")
        return df

    def _fetch_nifty_candles(self) -> Optional[pd.DataFrame]:
        """Fetch Nifty spot 5-min candles — 60 days history"""
        try:
            today     = date.today()
            from_date = (today - timedelta(days=60)).strftime("%Y-%m-%d")
            today_str = today.strftime("%Y-%m-%d")

            data = {
                "symbol":      "NSE:NIFTY50-INDEX",
                "resolution":  "5",          # 5-minute candles
                "date_format": "1",
                "range_from":  from_date,
                "range_to":    today_str,
                "cont_flag":   "1"
            }
            response = self.fyers.history(data=data)
            if response.get("s") != "ok":
                logger.debug(f"RSI2 candle fetch failed: {response.get('message')}")
                return None

            candles = response.get("candles", [])
            if not candles:
                return None

            df = pd.DataFrame(
                candles,
                columns=["timestamp", "open", "high", "low", "close", "volume"]
            )
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
            df = df.sort_values("timestamp").reset_index(drop=True)
            return df

        except Exception as e:
            logger.error(f"RSI2 fetch error: {e}")
            return None

    def _calculate_rsi2(self, close: np.ndarray) -> np.ndarray:
        """Calculate RSI with period 2"""
        period = RSI_PERIOD
        n      = len(close)
        rsi    = np.full(n, np.nan)

        deltas = np.diff(close)
        gains  = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)

        avg_gain = np.mean(gains[:period])
        avg_loss = np.mean(losses[:period])

        for i in range(period, n - 1):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            if avg_loss == 0:
                rsi[i + 1] = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi[i + 1] = 100.0 - (100.0 / (1.0 + rs))

        return rsi

    def _calculate_sma200(self, close: np.ndarray) -> np.ndarray:
        """Calculate 200 SMA"""
        sma = np.full(len(close), np.nan)
        for i in range(SMA_PERIOD - 1, len(close)):
            sma[i] = np.mean(close[i - SMA_PERIOD + 1:i + 1])
        return sma

    def _get_atm_strike(self, spot: float) -> int:
        return int(round(spot / 50) * 50)

    def _fetch_daily_candles(self):
        try:
            today = date.today()
            from_date = (today - timedelta(days=400)).strftime("%Y-%m-%d")
            data = {"symbol": "NSE:NIFTY50-INDEX", "resolution": "D", "date_format": "1",
                    "range_from": from_date, "range_to": today.strftime("%Y-%m-%d"), "cont_flag": "1"}
            response = self.fyers.history(data=data)
            if response.get("s") != "ok":
                return None
            candles = response.get("candles", [])
            if not candles:
                return None
            return pd.DataFrame(candles, columns=["timestamp","open","high","low","close","volume"])
        except Exception as e:
            logger.error(f"RSI2 daily fetch error: {e}")
            return None

    def _get_sma200_daily(self):
        today = date.today()
        if getattr(self, "_sma200_date", None) == today and getattr(self, "_sma200_cache", None) is not None:
            return self._sma200_cache
        dfx = self._fetch_daily_candles()
        if dfx is None or len(dfx) < SMA_PERIOD:
            logger.warning("RSI2: not enough daily candles for SMA200")
            return None
        sma = dfx["close"].astype(float).rolling(SMA_PERIOD).mean().iloc[-1]
        self._sma200_cache = round(float(sma), 2)
        self._sma200_date = today
        logger.info(f"RSI2 daily SMA200 refreshed: {self._sma200_cache}")
        return self._sma200_cache

    def _build_option_symbol(self, strike: int, option_type: str) -> str:
        from strategies.options_selector import build_fyers_option_symbol
        weekly = get_expiry_dates()["weekly"]
        return build_fyers_option_symbol(weekly, strike, option_type)

    def scan(self, nifty_spot: float) -> Optional[dict]:
        """
        Scan for RSI2 signal on latest completed 5-min candle.
        Returns trade dict or None.
        """
        if not self.fyers:
            return None

        df = self._get_candles_cached()
        if df is None or len(df) < SMA_PERIOD + 10:
            logger.debug("RSI2: Not enough candle data")
            return None

        close  = df["close"].values.astype(float)
        sma200_daily = self._get_sma200_daily()
        rsi2   = self._calculate_rsi2(close)

        # Get today's candles
        today_df = df[df["timestamp"].dt.date == date.today()]
        if len(today_df) < 3:
            logger.debug("RSI2: Not enough today candles")
            return None

        # Latest completed candle index
        last_idx   = today_df.index[-2]
        last_rsi   = rsi2[last_idx]
        last_sma   = sma200_daily
        last_close = close[last_idx]
        last_time  = df.iloc[last_idx]["timestamp"]

        if last_sma is None or np.isnan(last_rsi):
            logger.debug(f"RSI2: NaN values — RSI:{last_rsi} SMA:{last_sma}")
            return None

        logger.info(
            f"RSI2 Check | Spot:{last_close:.2f} "
            f"SMA200:{last_sma:.2f} RSI2:{last_rsi:.2f} "
            f"Time:{last_time.strftime('%H:%M')}"
        )

        atm = self._get_atm_strike(nifty_spot)

        # CE Signal — bullish bounce
        if last_close > last_sma and last_rsi < RSI_OVERSOLD:
            symbol = self._build_option_symbol(atm, "CE")
            logger.info(
                f"RSI2 CE SIGNAL — Spot:{last_close} > SMA:{last_sma:.2f} "
                f"RSI:{last_rsi:.2f} < {RSI_OVERSOLD}"
            )
            return {
                "action":      "TRADE",
                "symbol":      symbol,
                "strike":      atm,
                "option_type": "CE",
                "expiry":      get_expiry_dates()["weekly_str"],
                "direction":   "BUY",
                "quantity":    RSI2_QUANTITY,
                "strategy":    "RSI2",
                "signal_type": "BULLISH_BOUNCE",
                "sma200":      round(last_sma, 2),
                "rsi2":        round(last_rsi, 2),
                "spot":        last_close,
                "reasoning": (
                    f"RSI2 bullish bounce: Nifty {last_close:.2f} > 200SMA {last_sma:.2f}. "
                    f"RSI(2)={last_rsi:.2f} < {RSI_OVERSOLD} — oversold. BUY {atm}CE."
                )
            }

        # PE Signal — bearish bounce
        if last_close < last_sma and last_rsi > RSI_OVERBOUGHT:
            symbol = self._build_option_symbol(atm, "PE")
            logger.info(
                f"RSI2 PE SIGNAL — Spot:{last_close} < SMA:{last_sma:.2f} "
                f"RSI:{last_rsi:.2f} > {RSI_OVERBOUGHT}"
            )
            return {
                "action":      "TRADE",
                "symbol":      symbol,
                "strike":      atm,
                "option_type": "PE",
                "expiry":      get_expiry_dates()["weekly_str"],
                "direction":   "BUY",
                "quantity":    RSI2_QUANTITY,
                "strategy":    "RSI2",
                "signal_type": "BEARISH_BOUNCE",
                "sma200":      round(last_sma, 2),
                "rsi2":        round(last_rsi, 2),
                "spot":        last_close,
                "reasoning": (
                    f"RSI2 bearish bounce: Nifty {last_close:.2f} < 200SMA {last_sma:.2f}. "
                    f"RSI(2)={last_rsi:.2f} > {RSI_OVERBOUGHT} — overbought. BUY {atm}PE."
                )
            }

        logger.debug(
            f"RSI2: No signal — RSI:{last_rsi:.2f} SMA:{last_sma:.2f} Spot:{last_close:.2f}"
        )
        return None

    def should_exit(self, position: dict, nifty_spot: float) -> Optional[str]:
        """
        Check if an RSI2 position should be exited.
        Returns exit reason string or None.
        """
        if not self.fyers:
            return None

        df = self._get_candles_cached()
        if df is None or len(df) < SMA_PERIOD + 10:
            return None

        close  = df["close"].values.astype(float)
        sma200_daily = self._get_sma200_daily()
        rsi2   = self._calculate_rsi2(close)

        today_idx = df[df["timestamp"].dt.date == date.today()].index
        if len(today_idx) < 2:
            return None

        last_idx   = today_idx[-2]
        last_rsi   = rsi2[last_idx]
        last_sma   = sma200_daily
        last_close = close[last_idx]

        if last_sma is None or np.isnan(last_rsi):
            return None

        option_type = position.get("option_type", "CE")

        if option_type == "CE":
            if last_rsi > RSI_OVERBOUGHT:
                return f"RSI2 exit — RSI({last_rsi:.2f}) > {RSI_OVERBOUGHT}"
            if last_close < last_sma:
                return f"RSI2 SL — Spot({last_close:.2f}) < SMA200({last_sma:.2f})"

        elif option_type == "PE":
            if last_rsi < RSI_OVERSOLD:
                return f"RSI2 exit — RSI({last_rsi:.2f}) < {RSI_OVERSOLD}"
            if last_close > last_sma:
                return f"RSI2 SL — Spot({last_close:.2f}) > SMA200({last_sma:.2f})"

        return None


rsi2_scanner = RSI2Scanner()
