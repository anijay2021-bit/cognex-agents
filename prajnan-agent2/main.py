import time
import signal
import schedule
from datetime import datetime
from loguru import logger
from config.settings import settings
from core.database import init_db
from brokers.angelone_connector import angelone_connector
from brokers.angelone_data import angelone_data
from brokers.fyers_connector import fyers_connector
from risk.risk_guard import risk_guard
from notify.telegram_notifier import telegram
from notify.telegram_commands import SimpleCommandChecker
from strategies.strategy_engine import strategy_engine
from core.order_executor import order_executor
from dashboard.app import run_dashboard


class CognexOrchestrator:

    def __init__(self):
        self.running     = True
        self.paused      = False
        self.cmd_checker = SimpleCommandChecker(orchestrator=self)

    def start(self):
        logger.info("=" * 50)
        logger.info("Prajñān2 Agent Starting...")
        logger.info(f"Mode: {settings.trading_mode}")
        logger.info("Data: AngelOne SmartAPI — father's account")
        logger.info("=" * 50)

        init_db()

        import threading
        threading.Thread(target=run_dashboard, daemon=True).start()
        logger.info("Dashboard started on port 8081")

        data_ok = angelone_data.connect()
        if data_ok:
            logger.success("AngelOne data connected")
            strategy_engine.update_angelone(angelone_data)
        else:
            logger.error("AngelOne data FAILED — no market data!")

        time.sleep(3)  # avoid rate limit between logins
        exec_ok = angelone_connector.connect()
        if exec_ok:
            logger.success("AngelOne execution connected")
        else:
            logger.error("AngelOne execution FAILED — orders will not execute!")

        try:
            fyers_ok = fyers_connector.connect()
        except Exception as e:
            logger.warning(f"Fyers connect error: {e}")
            fyers_ok = False
        if not fyers_ok:
            try:
                from brokers.fyers_auto_auth import send_auth_reminder
                send_auth_reminder()
                logger.info("Fyers auth reminder sent via Telegram")
            except Exception as ae:
                logger.warning(f"Could not send Fyers auth reminder: {ae}")
        self._setup_schedule()

        telegram.send_message(
            f"🚀 Prajñān2 Agent Started\n"
            f"Mode: {'📝 PAPER' if settings.is_paper_mode else '🔴 LIVE'}\n"
            f"Data: {'✅ AngelOne' if data_ok else '❌ Failed'}\n"
            f"Exec: {'✅ AngelOne' if exec_ok else '❌ Failed'}\n"
            f"Strategy: RSI2(2) + SMA200 — 5min\n"
            f"Account: {settings.angelone_client_id}\n"
            f"Fyers LTP: OK" if fyers_ok else f"Fyers LTP: Not connected"
        )

        logger.info("Prajñān2 Agent running")
        counter = 0
        while self.running:
            try:
                schedule.run_pending()
                counter += 1
                if counter % 5 == 0:
                    self.cmd_checker.check_commands()
                time.sleep(1)
                if risk_guard.is_emergency_stopped():
                    logger.critical("Emergency stop active")
            except KeyboardInterrupt:
                self.shutdown()
                break
            except Exception as e:
                logger.error(f"Main loop error: {e}")
                time.sleep(5)

    def _setup_schedule(self):
        schedule.every(1).minutes.do(self.decision_cycle)
        schedule.every().day.at("09:10").do(self.morning_startup)
        schedule.every().day.at("15:25").do(self.eod_squareoff)
        schedule.every().day.at("03:00").do(self.fyers_daily_reconnect)
        logger.info("Scheduler configured")

    def fyers_daily_reconnect(self):
        """Daily 03:00 UTC / 08:30 IST: reconnect Fyers or send auth reminder."""
        logger.info("Fyers daily reconnect check 03:00 UTC / 08:30 IST")
        try:
            ok = fyers_connector.connect()
            if ok:
                logger.info("Fyers daily reconnect: token valid - OK")
            else:
                logger.warning("Fyers daily: token expired - sending auth reminder")
                from brokers.fyers_auto_auth import send_auth_reminder
                send_auth_reminder()
        except Exception as e:
            logger.warning(f"Fyers daily reconnect error: {e}")
            try:
                from brokers.fyers_auto_auth import send_auth_reminder
                send_auth_reminder()
            except Exception as ae:
                logger.warning(f"Could not send Fyers auth reminder: {ae}")

    def morning_startup(self):
        logger.info("Morning startup — reconnecting AngelOne")
        angelone_data.connect()
        strategy_engine.update_angelone(angelone_data)
        angelone_connector.connect()
        telegram.send_message("🌅 Agent2 morning startup complete")

    def decision_cycle(self):
        now = datetime.now()
        logger.info(f"Decision cycle — {now.strftime('%H:%M')} UTC")

        if self.paused:
            logger.info("Agent paused — skipping cycle")
            return

        try:
            snapshot = angelone_data.get_full_market_snapshot()
            nifty    = snapshot.get("nifty_spot", 0)
            vix      = snapshot.get("vix", 0)

            if nifty == 0:
                logger.warning("Nifty spot = 0 — data issue, skipping")
                return

            logger.info(f"Nifty:{nifty} VIX:{vix}")

            if vix > settings.vix_ceiling and settings.vix_ceiling > 0:
                logger.warning(
                    f"VIX {vix} > ceiling {settings.vix_ceiling} — no new trades"
                )
                return

            signals = strategy_engine.run(snapshot)

            if not signals:
                logger.info("No trade: No signals")
                return

            # Guard: skip new BUY if already in a position
            if order_executor.open_positions:
                logger.info(
                    f"Already in position(s): {list(order_executor.open_positions.keys())}"
                    f" - skipping new entry signal"
                )
                return
            
            for signal in signals:
                logger.info(f"Signal: {signal}")
                if signal.get("action") == "BUY":
                    from strategies.options_selector import build_fyers_option_symbol
                    direction  = signal.get("direction", "CE")
                    strike     = signal.get("strike", 0)
                    expiry     = signal.get("expiry", "")
                    symbol    = build_fyers_option_symbol(expiry, strike, direction)
                    _opt_quotes = fyers_connector.get_quotes([symbol])
                    ltp         = _opt_quotes.get(symbol, {}).get("ltp", 0)
                    if ltp <= 0:
                        logger.warning(f"No LTP for {symbol} — skipping signal")
                        continue
                    trade = {
                        "action":        "TRADE",
                        "symbol":        symbol,
                        "strike":        strike,
                        "option_type":   direction,
                        "entry_price":   ltp,
                        "stop_loss":     round(ltp * 0.70, 2),
                        "target":        round(ltp * 1.50, 2),
                        "quantity":      signal.get("quantity", 650),
                        "expiry":        expiry,
                        "reasoning":     signal.get("reason", ""),
                        "strategy_used": "RSI2"
                    }
                    logger.info(f"Placing order: {trade}")
                    order_executor.execute(trade)
                elif signal.get("action") == "EXIT":
                    logger.info(f"EXIT signal: {signal}")

        except Exception as e:
            logger.error(f"Decision cycle error: {e}")

    def eod_squareoff(self):
        logger.info("EOD square-off triggered")
        order_executor.square_off_all(angelone_connector)
        telegram.send_message("🔔 Agent2 EOD square-off complete")

    def shutdown(self):
        logger.info("Shutting down Agent2...")
        self.running = False
        telegram.send_message("🛑 Prajñān2 Agent stopped")


def main():
    signal.signal(signal.SIGTERM, lambda s, f: orchestrator.shutdown())
    orchestrator.start()


orchestrator = CognexOrchestrator()

if __name__ == "__main__":
    main()
