import requests
from datetime import datetime
from loguru import logger
from config.settings import settings


class SimpleCommandChecker:
    def __init__(self, orchestrator=None):
        self.orchestrator = orchestrator
        self.base_url = f"https://api.telegram.org/bot{settings.telegram_bot_token}"
        self.last_update_id = 0
        self._get_last_update_id()

    def _get_last_update_id(self):
        try:
            resp = requests.get(f"{self.base_url}/getUpdates", params={"limit": 1, "timeout": 0}, timeout=5)
            data = resp.json()
            if data.get("ok") and data.get("result"):
                self.last_update_id = data["result"][-1]["update_id"]
            logger.info(f"Telegram command checker ready. Offset: {self.last_update_id}")
        except Exception as e:
            logger.debug(f"Command checker init: {e}")

    def check_commands(self):
        try:
            resp = requests.get(
                f"{self.base_url}/getUpdates",
                params={"offset": self.last_update_id + 1, "limit": 10, "timeout": 0},
                timeout=10
            )
            data = resp.json()
            if not data.get("ok"):
                return
            for update in data.get("result", []):
                self.last_update_id = update["update_id"]
                message = update.get("message", {})
                chat_id = str(message.get("chat", {}).get("id", ""))
                raw_text = message.get("text", "").strip()
                text = raw_text.upper()
                if chat_id != str(settings.telegram_chat_id):
                    continue
                logger.info(f"Command received: {text}")
                self._handle_command(text, raw_text, chat_id)
        except Exception as e:
            logger.debug(f"Command check error: {e}")

    def _send(self, chat_id, text):
        try:
            requests.post(
                f"{self.base_url}/sendMessage",
                json={"chat_id": chat_id, "text": text},
                timeout=10
            )
        except Exception as e:
            logger.debug(f"Send error: {e}")

    def _handle_command(self, text, raw_text, chat_id):
        if text in ["STATUS", "/STATUS"]:
            self._cmd_status(chat_id)
        elif text in ["VIX", "/VIX"]:
            self._cmd_vix(chat_id)
        elif text in ["PAUSE", "/PAUSE"]:
            self._cmd_pause(chat_id)
        elif text in ["RESUME", "/RESUME"]:
            self._cmd_resume(chat_id)
        elif text in ["STOP", "/STOP"]:
            self._cmd_stop(chat_id)
        elif text in ["TRADES", "/TRADES"]:
            self._cmd_trades(chat_id)
        elif text in ["SETTINGS", "/SETTINGS"]:
            self._cmd_settings(chat_id)
        elif text in ["HELP", "/HELP", "/START"]:
            self._cmd_help(chat_id)
        elif text.startswith("FYERS_AUTH"):
            url = raw_text[10:].strip()
            self._cmd_fyers_auth(chat_id, url)
        else:
            self._send(chat_id, f"Command not recognised: {text}\nType HELP to see all commands.")

    def _cmd_help(self, chat_id):
        self._send(chat_id,
            "COGNEX Agent Commands\n"
            "STATUS   - positions and P&L\n"
            "TRADES   - today trade list\n"
            "VIX      - live market snapshot\n"
            "SETTINGS - strategy settings\n"
            "FYERS_AUTH url - refresh token\n"
            "PAUSE    - pause trading\n"
            "RESUME   - resume trading\n"
            "STOP     - emergency halt\n"
            f"Mode: {'PAPER' if settings.is_paper_mode else 'LIVE'}\n"
            f"Time: {datetime.now().strftime('%d-%b %H:%M IST')}"
        )

    def _cmd_settings(self, chat_id):
        try:
            from strategies.rsi2_scanner import (
                RSI_PERIOD, SMA_PERIOD, RSI_OVERSOLD,
                RSI_OVERBOUGHT, RSI2_QUANTITY, RSI2_LOTS, TIMEFRAME
            )
            msg = (
                "COGNEX Strategy Settings\n"
                "========================\n"
                f"Strategy:       RSI2 + SMA200\n"
                f"Timeframe:      {TIMEFRAME}-min candles\n"
                f"RSI Period:     {RSI_PERIOD}\n"
                f"SMA Period:     {SMA_PERIOD}\n"
                f"RSI Oversold:   {RSI_OVERSOLD} (CE entry)\n"
                f"RSI Overbought: {RSI_OVERBOUGHT} (PE entry)\n"
                f"Quantity:       {RSI2_QUANTITY} ({RSI2_LOTS} lots)\n"
                "========================\n"
                f"CE Entry: Spot > SMA{SMA_PERIOD} AND RSI < {RSI_OVERSOLD}\n"
                f"PE Entry: Spot < SMA{SMA_PERIOD} AND RSI > {RSI_OVERBOUGHT}\n"
                f"CE Exit:  RSI > {RSI_OVERBOUGHT} OR Spot < SMA{SMA_PERIOD}\n"
                f"PE Exit:  RSI < {RSI_OVERSOLD} OR Spot > SMA{SMA_PERIOD}\n"
                "========================\n"
                f"Mode: {'PAPER' if settings.is_paper_mode else 'LIVE'}\n"
                f"{datetime.now().strftime('%d-%b %H:%M IST')}"
            )
            self._send(chat_id, msg)
        except Exception as e:
            self._send(chat_id, f"Settings error: {e}")

    def _cmd_status(self, chat_id):
        try:
            from core.database import SessionLocal, Trade
            from datetime import date
            db = SessionLocal()
            today = str(date.today())
            trades = db.query(Trade).filter(Trade.entry_time >= today).all()
            db.close()
            total       = len(trades)
            winning     = len([t for t in trades if (t.pnl_rs or 0) > 0])
            losing      = len([t for t in trades if (t.pnl_rs or 0) < 0])
            net_pnl     = sum(t.pnl_rs or 0 for t in trades)
            open_trades = [t for t in trades if t.status == "OPEN"]
            paused      = self.orchestrator.paused if self.orchestrator else False
            import os
            stopped     = os.path.exists("logs/EMERGENCY_STOP")
            self._send(chat_id,
                f"Agent Status\n"
                f"Mode: {'PAPER' if settings.is_paper_mode else 'LIVE'}\n"
                f"Trading: {'STOPPED' if stopped else ('PAUSED' if paused else 'ACTIVE')}\n"
                f"Today Trades: {total}\n"
                f"Winning: {winning} | Losing: {losing}\n"
                f"Net PnL: Rs{net_pnl:.2f}\n"
                f"Open Positions: {len(open_trades)}\n"
                f"{datetime.now().strftime('%d-%b %H:%M IST')}"
            )
        except Exception as e:
            self._send(chat_id, f"Status error: {e}")

    def _cmd_trades(self, chat_id):
        try:
            from core.database import SessionLocal, Trade
            from datetime import date
            db = SessionLocal()
            today = str(date.today())
            trades = db.query(Trade).filter(Trade.entry_time >= today).all()
            db.close()
            if not trades:
                self._send(chat_id, f"No trades today.\n{date.today().strftime('%d-%b-%Y')}")
                return
            lines = [f"Today Trades {date.today().strftime('%d-%b-%Y')}\n"]
            total_pnl = 0
            for i, t in enumerate(trades, 1):
                pnl        = t.pnl_rs or 0
                total_pnl += pnl
                sl         = t.stop_loss_rs or 0
                status     = t.status or "OPEN"
                pnl_str    = f"Rs{pnl:+.0f}" if pnl != 0 else "Open"
                entry_time = t.entry_time.strftime("%H:%M") if t.entry_time else "--"
                lines.append(
                    f"{i}. {t.symbol}\n"
                    f"   {t.direction} @ Rs{t.entry_price:.2f} | {entry_time}\n"
                    f"   SL: Rs{sl:.2f} | {status}\n"
                    f"   PnL: {pnl_str}\n"
                )
            lines.append(f"Net PnL: Rs{total_pnl:+.0f}")
            self._send(chat_id, "\n".join(lines))
        except Exception as e:
            self._send(chat_id, f"Trades error: {e}")

    def _cmd_vix(self, chat_id):
        try:
            from brokers.fyers_connector import fyers_connector
            if not fyers_connector._connected:
                fyers_connector.connect()
            snapshot = fyers_connector.get_full_market_snapshot()
            nifty    = snapshot.get("nifty", {})
            bnf      = snapshot.get("banknifty", {})
            vix      = snapshot.get("vix", 0)
            if vix < 15:
                vix_status = "Normal"
            elif vix < 20:
                vix_status = "Elevated"
            elif vix < settings.vix_ceiling:
                vix_status = "High — Trading allowed"
            else:
                vix_status = "ABOVE CEILING — No new trades"
            self._send(chat_id,
                f"Live Market Snapshot\n"
                f"Nifty:     {nifty.get('spot', 0):,.2f}\n"
                f"BankNifty: {bnf.get('spot', 0):,.2f}\n"
                f"VIX:       {vix:.2f} — {vix_status}\n"
                f"PCR:       {nifty.get('pcr', 0):.3f}\n"
                f"MaxPain:   {nifty.get('max_pain', 0):,.0f}\n"
                f"CE Wall:   {nifty.get('ce_wall', 0):,.0f}\n"
                f"PE Wall:   {nifty.get('pe_wall', 0):,.0f}\n"
                f"{datetime.now().strftime('%d-%b %H:%M IST')}"
            )
        except Exception as e:
            self._send(chat_id, f"Market data error: {e}")

    def _cmd_pause(self, chat_id):
        if self.orchestrator:
            self.orchestrator.paused = True
        self._send(chat_id, "Trading PAUSED\nStill monitoring. Type RESUME to continue.")
        logger.info("Trading paused by Telegram")

    def _cmd_resume(self, chat_id):
        from risk.risk_guard import risk_guard
        risk_guard.clear_emergency_stop()
        if self.orchestrator:
            self.orchestrator.paused = False
        self._send(chat_id, "Trading RESUMED\nAgent is now active.")
        logger.info("Trading resumed by Telegram")

    def _cmd_stop(self, chat_id):
        from risk.risk_guard import risk_guard
        risk_guard.emergency_stop()
        self._send(chat_id, "EMERGENCY STOP ACTIVATED\nAll trading halted.\nType RESUME to restart.")
        logger.critical("Emergency stop by Telegram")

    def _cmd_fyers_auth(self, chat_id, redirect_url):
        try:
            from brokers.fyers_auto_auth import complete_auth_from_url
            from brokers.fyers_connector import fyers_connector
            ok = complete_auth_from_url(redirect_url)
            if ok:
                fyers_connector._connected = False
                fyers_connector.connect()
                try:
                    from strategies.strategy_engine import strategy_engine
                    strategy_engine.update_fyers(fyers_connector.fyers)
                    logger.info("RSI2 scanner fyers updated after Telegram auth")
                except Exception as ue:
                    logger.warning(f"Could not update scanner fyers: {ue}")
                self._send(chat_id, "Fyers token refreshed successfully!\nAgent connected to live market data.")
                logger.info("Fyers token refreshed via Telegram")
            else:
                self._send(chat_id, "Fyers auth failed\nPlease try again with full redirect URL.")
        except Exception as e:
            self._send(chat_id, f"Auth error: {e}")
