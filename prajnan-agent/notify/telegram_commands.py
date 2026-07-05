import sys, os, requests
from datetime import datetime, date
from loguru import logger
PROJECT_ROOT = "/home/anijay2021/prajnan-agent"
if PROJECT_ROOT not in sys.path: sys.path.insert(0, PROJECT_ROOT)
from config.settings import settings

class SimpleCommandChecker:
    def __init__(self, orchestrator=None):
        self.orchestrator = orchestrator
        self.base_url = f"https://api.telegram.org/bot{settings.telegram_bot_token}"
        self.last_update_id = self._get_last_update_id()

    def _get_last_update_id(self):
        try:
            r = requests.get(f"{self.base_url}/getUpdates", timeout=5).json()
            if r["ok"] and r["result"]: return r["result"][-1]["update_id"] + 1
            return 0
        except: return 0

    def check_commands(self):
        try:
            url = f"{self.base_url}/getUpdates?offset={self.last_update_id}&limit=10"
            r = requests.get(url, timeout=5).json()
            if not r["ok"]: return
            for update in r["result"]:
                self.last_update_id = update["update_id"] + 1
                if "message" in update and "text" in update["message"]:
                    raw_text = update["message"]["text"]
                    chat_id = update["message"]["chat"]["id"]
                    self.handle_message(raw_text, chat_id)
        except Exception as e: logger.debug(f"Command check error: {e}")

    def _send(self, chat_id, text):
        try:
            requests.post(f"{self.base_url}/sendMessage", json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
        except: pass

    def handle_message(self, raw_text, chat_id):
        text = raw_text.upper().strip()
        logger.info(f"Command received: {text}")
        if text in ["STATUS", "/STATUS"]: self._cmd_status(chat_id)
        elif text in ["VIX", "/VIX"]: self._cmd_vix(chat_id)
        elif text in ["PAUSE", "/PAUSE"]: self._cmd_pause(chat_id)
        elif text in ["RESUME", "/RESUME"]: self._cmd_resume(chat_id)
        elif text in ["STOP", "/STOP"]: self._cmd_stop(chat_id)
        elif text in ["TRADES", "/TRADES"]: self._cmd_trades(chat_id)
        elif text in ["SETTINGS", "/SETTINGS"]: self._cmd_settings(chat_id)
        elif text in ["HELP", "/HELP", "/START"]: self._cmd_help(chat_id)
        elif text.startswith("FYERS_AUTH"):
            url = raw_text[10:].strip().strip("[] ")
            self._cmd_fyers_auth(chat_id, url)
        elif raw_text.strip().startswith("https://") and "auth_code" in raw_text:
            # User pasted Fyers redirect URL directly - no prefix needed
            self._cmd_fyers_auth(chat_id, raw_text.strip())
        else:
            self._send(chat_id, "Unknown command. Send /HELP for list.")

    def _cmd_help(self, chat_id):
        msg = (
            "?? <b>COGNEX Agent Commands</b>\n"
            "?????????????????????\n"
            "STATUS   - positions and P&L\n"
            "TRADES   - today trade list\n"
            "VIX      - live market snapshot\n"
            "SETTINGS - strategy settings\n"
            "FYERS_AUTH url - refresh token\n"
            "PAUSE    - pause trading\n"
            "RESUME   - resume trading\n"
            "STOP     - emergency halt\n\n"
            f"Mode: {'PAPER' if settings.is_paper_mode else 'LIVE'}\n"
            f"Time: {datetime.now().strftime('%d-%b %H:%M IST')}"
        )
        self._send(chat_id, msg)

    def _cmd_status(self, chat_id):
        try:
            from core.database import SessionLocal, Trade
            db = SessionLocal()
            today = str(date.today())
            trades = db.query(Trade).filter(Trade.entry_time >= today).all()
            all_open = db.query(Trade).filter(Trade.status == "OPEN").all()
            db.close()
            net_pnl = sum(t.pnl_rs or 0 for t in trades)
            unrealized_pnl = 0.0
            if all_open:
                try:
                    from strategies.rsi2_scanner import rsi2_scanner as _rs
                    for _ot in all_open:
                        _ltp = _rs._get_option_ltp(_ot.symbol) or 0.0
                        unrealized_pnl += round((_ltp - (_ot.entry_price or 0)) * (_ot.quantity or 0), 2)
                except Exception:
                    pass
            open_count = len(all_open)
            paused = self.orchestrator.paused if self.orchestrator else False
            msg = (
                f"\U0001f916 <b>Agent Status</b>\n"
                    f"\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
                f"Mode: {'PAPER' if settings.is_paper_mode else 'LIVE'}\n"
                    f"Trading: {'PAUSED \u23f8' if paused else 'ACTIVE \u2705'}\n"
                f"Today Trades: {len(trades)}\n"
                f"Open Positions: {open_count}\n"
                f"Net PnL: <b>Rs{net_pnl:.2f}</b>  Unrealized: <b>Rs{unrealized_pnl:+.2f}</b>\n"
                f"Time: {datetime.now().strftime('%d-%b %H:%M IST')}"
            )
            self._send(chat_id, msg)
        except Exception as e: self._send(chat_id, f"Status error: {e}")

    def _cmd_vix(self, chat_id):
        try:
            from brokers.fyers_connector import fyers_connector
            snapshot = fyers_connector.get_full_market_snapshot()
            vix = snapshot.get("vix", 0)
            vix_status = "Normal" if vix < 18 else "High"
            self._send(chat_id, f"\U0001f4ca <b>VIX Report</b>\n\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\nIndia VIX: {vix:.2f}\nStatus: {vix_status}")
        except Exception as e: self._send(chat_id, f"VIX error: {e}")

    def _cmd_trades(self, chat_id):
        try:
            from core.database import SessionLocal, Trade
            db = SessionLocal()
            today = str(date.today())
            trades = db.query(Trade).filter(Trade.entry_time >= today).all()
            cf_open = db.query(Trade).filter(Trade.status == "OPEN", Trade.entry_time < today).all()
            db.close()
            if not trades and not cf_open:
                return self._send(chat_id, "No trades today and no open positions.")
            lines = []
            if trades:
                lines.append(f"📊 <b>Today Trades ({date.today().strftime('%d-%b')})</b>")
                for i, t in enumerate(trades, 1):
                    pnl = t.pnl_rs or 0
                    lines.append(f"{i}. {t.symbol} | {t.direction}\n    PnL: Rs{pnl:.0f} | {t.status}")
            if cf_open:
                lines.append(f"\n⚠️ <b>Carryforward Open Positions</b>")
                for t in cf_open:
                    d = t.entry_time.strftime('%d-%b') if t.entry_time else "?"
                    lines.append(f"  {t.symbol} | {t.direction} | OPEN since {d}")
            self._send(chat_id, "\n".join(lines))
        except Exception as e: self._send(chat_id, f"Trades error: {e}")

    def _cmd_pause(self, chat_id):
        if self.orchestrator: self.orchestrator.paused = True
        self._send(chat_id, "? Trading Paused.")

    def _cmd_resume(self, chat_id):
        if self.orchestrator: self.orchestrator.paused = False
        self._send(chat_id, "?? Trading Resumed.")

    def _cmd_stop(self, chat_id):
        if self.orchestrator: self.orchestrator.running = False
        self._send(chat_id, "?? Emergency Stop Triggered.")

    def _cmd_settings(self, chat_id):
        self._send(chat_id, f"?? Strategy: RSI2 + SMA200\nThresholds: CE < 10, PE > 90\nMode: PAPER")

    def _cmd_fyers_auth(self, chat_id, redirect_url):
        try:
            from brokers.fyers_auto_auth import complete_auth_from_url
            from brokers.fyers_connector import fyers_connector
            ok = complete_auth_from_url(redirect_url)
            if ok:
                fyers_connector.connect()
                self._send(chat_id, "? Fyers token refreshed successfully!\nStrategies are now LIVE.")
            else:
                self._send(chat_id, "? Fyers auth failed\nPlease try again with fresh url.")
        except Exception as e: logger.error(f"Auth cmd error: {e}")
