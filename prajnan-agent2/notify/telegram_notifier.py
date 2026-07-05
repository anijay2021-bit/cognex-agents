import asyncio
from datetime import datetime
from loguru import logger
from config.settings import settings

class TelegramNotifier:
    def __init__(self):
        self.bot_token = settings.telegram_bot_token
        self.chat_id = settings.telegram_chat_id
        self.bot = None
        if self.bot_token:
            try:
                from telegram import Bot
                self.bot = Bot(token=self.bot_token)
            except Exception as e:
                logger.warning(f"Telegram bot init failed: {e}")

    async def _send(self, message, parse_mode=None):
        if not self.bot:
            logger.info(f"[TELEGRAM] {message[:100]}")
            return
        try:
            await self.bot.send_message(chat_id=self.chat_id, text=message, parse_mode=parse_mode)
        except Exception as e:
            logger.error(f"Telegram send error: {e}")

    def send(self, message, parse_mode=None):
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self._send(message, parse_mode))
            else:
                loop.run_until_complete(self._send(message, parse_mode))
        except Exception:
            try:
                asyncio.run(self._send(message))
            except Exception as e:
                logger.info(f"[TELEGRAM] {message[:100]}")

    def send_trade_alert(self, action, symbol, direction, quantity, price, strategy, reason, pnl=None, mode="PAPER"):
        mode_tag = "PAPER" if mode == "PAPER" else "LIVE"
        icon = "✅" if action == "OPENED" else ("💰" if action == "CLOSED" else "🚫")
        msg = (
            f"{icon} <b>TRADE {action}</b> — {mode_tag}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>{direction}</b> {quantity} x {symbol}\n"
            f"Price: Rs{price:.2f}\n"
            f"Strategy: {strategy}\n"
        )
        if pnl is not None:
            pnl_icon = "🟢" if pnl >= 0 else "🔴"
            msg += f"{pnl_icon} PnL: Rs{pnl:.2f}\n"
        msg += (
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"<i>{reason[:200]}</i>\n"
            f"{datetime.now().strftime('%d-%b %H:%M IST')}"
        )
        self.send(msg)

    def send_morning_briefing(self, nifty, banknifty, vix, pcr, max_pain, crude, usdinr, top_news, mode="PAPER"):
        mode_tag = "PAPER MODE" if mode == "PAPER" else "LIVE MODE"
        vix_status = "Normal" if vix < 15 else ("Elevated" if vix < 20 else "HIGH — Cautious")
        msg = (
            f"🌅 <b>COGNEX Morning Briefing</b>\n"
            f"{datetime.now().strftime('%A, %d %B %Y')} — {mode_tag}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"Nifty 50:  Rs{nifty:,.0f}\n"
            f"BankNifty: Rs{banknifty:,.0f}\n"
            f"India VIX: {vix:.2f} — {vix_status}\n"
            f"PCR: {pcr:.2f} | MaxPain: Rs{max_pain:,.0f}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"Crude: ${crude:.1f}/bbl | USD/INR: Rs{usdinr:.2f}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"<i>{top_news[:300]}</i>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"Agent is watching. I will alert you on every trade."
        )
        self.send(msg)

    def send_risk_alert(self, alert_type, details):
        msg = (
            f"⚠️ <b>RISK ALERT: {alert_type}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"{details}\n"
            f"{datetime.now().strftime('%d-%b %H:%M IST')}"
        )
        self.send(msg)

    def send_evening_summary(self, total_trades, winning, losing, gross_pnl, net_pnl, mode="PAPER"):
        mode_tag = "PAPER" if mode == "PAPER" else "LIVE"
        pnl_icon = "🟢" if net_pnl >= 0 else "🔴"
        win_rate = f"{(winning/total_trades*100):.0f}%" if total_trades > 0 else "N/A"
        msg = (
            f"🌙 <b>Daily Summary</b> — {mode_tag}\n"
            f"{datetime.now().strftime('%d %B %Y')}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"Trades: {total_trades} (✅{winning} wins 🔴{losing} losses)\n"
            f"Win Rate: {win_rate}\n"
            f"{pnl_icon} <b>Net PnL: Rs{net_pnl:.2f}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"Good night. Monitoring continues."
        )
        self.send(msg)

    def send_error(self, component, error):
        msg = (
            f"🔧 <b>System Error</b>\n"
            f"Component: {component}\n"
            f"Error: {error[:300]}\n"
            f"{datetime.now().strftime('%H:%M IST')}\n"
            f"<i>Agent attempting self-repair...</i>"
        )
        self.send(msg)

    def send_message(self, text, parse_mode=None):
        self.send(text, parse_mode=parse_mode)

telegram = TelegramNotifier()
