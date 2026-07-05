from loguru import logger
from strategies.rsi2_scanner import rsi2_scanner

class StrategyEngine:

    def __init__(self):
        self.ao = None

    def update_angelone(self, angelone_data):
        self.ao = angelone_data
        rsi2_scanner.update_angelone(angelone_data)
        logger.info("StrategyEngine: AngelOne data connector updated")

    def run(self, snapshot: dict) -> list:
        spot = snapshot.get("nifty_spot", 0)
        logger.info(f"Running RSI2 scan | Spot: {spot}")
        signals = []
        result  = rsi2_scanner.scan(spot_price=spot)
        if result:
            signals.append(result)
        return signals

strategy_engine = StrategyEngine()
