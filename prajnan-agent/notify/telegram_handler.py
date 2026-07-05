import asyncio
import threading
from datetime import datetime
from loguru import logger

try:
    from telegram import Update
    from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False

from config.settings import settings

class TelegramCommandHandler:
    """
    Listens for commands from Kiran's phone and acts on them.
    Commands:
      STOP   — emergency halt all trading
      STATUS — current positions and P&L
      PAUSE  — pause trading (keep monitoring)
      RESUME — resume trading
      VIX    — current market snapshot
      HELP   — list all commands
    """

    def __init__(self, orchestrator=None):
        self.orchestrator = orchestrator
        self.app = None
        self._thread = None

    def start(self):
        if not TELEGRAM_AVAILABLE:
            logger.warning("Telegram not available — command handler disabled")
            return
        if not settings.telegram_bot_token:
            logger.warning("No Telegram token — command handler disabled")
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("Telegram command handler started")

    def _run(self):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._start_bot())
        except Exception as e:
            logger.error(f"Telegram handler error: {e}")

    async def _start_bot(self):
        self.app = Application.builder().token(settings.telegram_bot_token).build()

        # Register handlers
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        self.app.add_handler(CommandHandler("start", self.cmd_start))
        self.app.add_handler(CommandHandler("help", self.cmd_help))
        self.app.add_handler(CommandHandler("status", self.cmd_status))
        self.app.add_handler(CommandHandler("stop", self.cmd_stop))
        self.app.add_handler(CommandHandler("pause", self.cmd_pause))
        self.app.add_handler(CommandHandler("resume", self.cmd_resume))
        self.app.add_handler(CommandHandler("vix", self.cmd_vix))

        logger.info("Telegram bot polling started")
        await self.app.run_polling(drop_pending_updates=True)

    def _is_authorised(self, update) -> bool:
        """Only Kiran can control the agent"""
        chat_id = str(update.effective_chat.id)
        return chat_id == str(settings.telegram_chat_id)

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle plain text messages — treat as commands"""
        if not self._is_authorised(update):
            return

        text = update.message.text.strip().upper()

        if text == "STOP":
            await self.cmd_stop(update, context)
        elif text == "STATUS":
            await self.cmd_status(update, context)
        elif text == "PAUSE":
            await self.cmd_pause(update, context)
        elif text == "RESUME":
            await self.cmd_resume(update, context)
        elif text == "VIX":
            await self.cmd_vix(update, context)
        elif text == "HELP":
            await self.cmd_help(update, context)
        else:
            await update.message.reply_text(
                f"Command not recognised: {text}\n"
                f"Type HELP to see all commands."
            )

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorised(update):
            return
        await update.message.reply_text(
            "🤖 <b>COGNEX Agent</b>\n"
            "I am your autonomous trading agent.\n\n"
            "Type HELP to see all commands.",
            parse_mode="HTML"
        )

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorised(update):
            return
        await update.message.reply_text(
            "🤖 <b>COGNEX Agent Commands</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "<b>STATUS</b> — positions and P&L\n"
            "<b>VIX</b> — live market snapshot\n"
            "<b>PAUSE</b> — pause trading\n"
            "<b>RESUME</b> — resume trading\n"
            "<b>STOP</b> — emergency halt\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"Mode: {'PAPER' if settings.is_paper_mode else 'LIVE'}\n"
            f"Time: {datetime.now().strftime('%d-%b %H:%M IST')}",
            parse_mode="HTML"
        )

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorised(update):
            return
        try:
            from core.database import SessionLocal, Trade, DailyPnL
            from datetime import date
            db = SessionLocal()
            today = str(date.today())
            trades = db.query(Trade).filter(
                Trade.entry_time >= today
            ).all()
            daily = db.query(DailyPnL).filter(
                DailyPnL.date == today
            ).first()
            db.close()

            total   = len(trades)
            winning = len([t for t in trades if (t.pnl_rs or 0) > 0])
            losing  = len([t for t in trades if (t.pnl_rs or 0) < 0])
            net_pnl = sum(t.pnl_rs or 0 for t in trades)
            open_trades = [t for t in trades if t.status == "OPEN"]

            paused = self.orchestrator.paused if self.orchestrator else False
            stopped = False
            try:
                import os
                stopped = os.path.exists("logs/EMERGENCY_STOP")
            except Exception:
                pass

            status_text = (
                f"📊 <b>Agent Status</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"Mode: {'PAPER' if settings.is_paper_mode else 'LIVE'}\n"
                f"Trading: {'🛑 STOPPED' if stopped else ('⏸ PAUSED' if paused else '✅ ACTIVE')}\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"Today's Trades: {total}\n"
                f"Winning: {winning} | Losing: {losing}\n"
                f"Net P&L: Rs{net_pnl:.2f}\n"
                f"Open Positions: {len(open_trades)}\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"{datetime.now().strftime('%d-%b %H:%M IST')}"
            )
            await update.message.reply_text(status_text, parse_mode="HTML")

        except Exception as e:
            await update.message.reply_text(f"Status error: {e}")

    async def cmd_stop(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorised(update):
            return
        try:
            from risk.risk_guard import risk_guard
            risk_guard.emergency_stop()
            await update.message.reply_text(
                "🛑 <b>EMERGENCY STOP ACTIVATED</b>\n"
                "All trading halted immediately.\n"
                "Open positions are NOT automatically closed.\n"
                "Check AngelOne app to manage open positions.\n\n"
                "To resume: type RESUME",
                parse_mode="HTML"
            )
            logger.critical("Emergency stop triggered by Telegram command")
        except Exception as e:
            await update.message.reply_text(f"Stop error: {e}")

    async def cmd_pause(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorised(update):
            return
        if self.orchestrator:
            self.orchestrator.paused = True
        await update.message.reply_text(
            "⏸ <b>Trading PAUSED</b>\n"
            "Agent is still monitoring news and market.\n"
            "No new trades will be placed.\n"
            "Type RESUME to continue trading.",
            parse_mode="HTML"
        )
        logger.info("Trading paused by Telegram command")

    async def cmd_resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorised(update):
            return
        try:
            from risk.risk_guard import risk_guard
            risk_guard.clear_emergency_stop()
        except Exception:
            pass
        if self.orchestrator:
            self.orchestrator.paused = False
        await update.message.reply_text(
            "▶️ <b>Trading RESUMED</b>\n"
            "Agent is now active and will trade\n"
            "when conditions are met.",
            parse_mode="HTML"
        )
        logger.info("Trading resumed by Telegram command")

    async def cmd_vix(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorised(update):
            return
        try:
            from brokers.fyers_connector import fyers_connector
            if not fyers_connector._connected:
                fyers_connector.connect()
            snapshot = fyers_connector.get_full_market_snapshot()
            nifty = snapshot.get("nifty", {})
            bnf   = snapshot.get("banknifty", {})
            vix   = snapshot.get("vix", 0)
            vix_status = "✅ Normal" if vix < 15 else ("⚠️ Elevated" if vix < 20 else "🚨 HIGH — No new trades")

            await update.message.reply_text(
                f"📈 <b>Live Market Snapshot</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"Nifty:     {nifty.get('spot', 0):,.2f}\n"
                f"BankNifty: {bnf.get('spot', 0):,.2f}\n"
                f"VIX:       {vix:.2f} — {vix_status}\n"
                f"PCR:       {nifty.get('pcr', 0):.3f}\n"
                f"MaxPain:   {nifty.get('max_pain', 0):,.0f}\n"
                f"CE Wall:   {nifty.get('ce_wall', 0):,.0f}\n"
                f"PE Wall:   {nifty.get('pe_wall', 0):,.0f}\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"{datetime.now().strftime('%d-%b %H:%M IST')}",
                parse_mode="HTML"
            )
        except Exception as e:
            await update.message.reply_text(f"Market data error: {e}")
