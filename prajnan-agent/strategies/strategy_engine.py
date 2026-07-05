import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from datetime import datetime
from loguru import logger
from config.settings import settings

try:
    from strategies.rsi2_scanner import rsi2_scanner
except ImportError:
    from rsi2_scanner import rsi2_scanner

try:
    from strategies.ema_obv_scanner import ema_obv_scanner
except ImportError:
    from ema_obv_scanner import ema_obv_scanner

from notify.telegram_notifier import telegram


class StrategyEngine:

    def __init__(self, fyers_model=None):
        self.fyers = fyers_model

    def update_fyers(self, fyers_model):
        self.fyers        = fyers_model
        rsi2_scanner.fyers     = fyers_model
        ema_obv_scanner.update_fyers(fyers_model)
        logger.info("StrategyEngine: Fyers model updated for all strategies")

    def run(self, snapshot: dict) -> list:
        spot    = snapshot.get("nifty_spot", 0) or snapshot.get("nifty", {}).get("spot", 0)
        vix     = snapshot.get("vix", 0)
        signals = []

        logger.info(f"StrategyEngine: Running all strategies | Spot:{spot} VIX:{vix}")

        # Strategy 1 — RSI2 mean reversion
        try:
            result = rsi2_scanner.scan(spot_price=spot)
            if result:
                result["strategy"] = "RSI2"
                signals.append(result)
                logger.info(f"RSI2 signal: {result.get('action')} {result.get('direction','')}")
        except Exception as e:
            logger.error(f"RSI2 scan error: {e}")

        # Strategy 2 — EMA crossover + OBV
        try:
            result = ema_obv_scanner.scan(spot_price=spot)
            if result:
                result["strategy"] = "EMA_OBV"
                signals.append(result)
                logger.info(f"EMA+OBV signal: {result.get('action')} {result.get('direction','')}")
        except Exception as e:
            logger.error(f"EMA+OBV scan error: {e}")

        if not signals:
            logger.info("StrategyEngine: No signals from any strategy")

        return signals


strategy_engine = StrategyEngine()
