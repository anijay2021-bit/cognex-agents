"""
fyers-auth-service - standalone daily Fyers token owner for the whole COGNEX
stack (nitin-agent, 18sma-agent, vwap-agent, prajnan-calendar-agent,
cognex-dashboard all read config/fyers_token.json from here).

Replaces the auth-refresh role that used to live inside prajnan-agent's
process (brokers/fyers_auto_auth.py + notify/telegram_commands.py FYERS_AUTH
handler + main.py's startup is_token_valid() check). Fyers requires a human
login once a day, so this service (1) checks token validity, (2) sends ONE
Telegram reminder per weekday at/after 08:30 IST when it's stale, and (3)
listens for the pasted-back redirect URL to complete the refresh.
"""
import datetime as dt
import threading
import time
from zoneinfo import ZoneInfo

from loguru import logger

from config.settings import settings
from fyers_auto_auth import is_token_valid, send_auth_reminder
from telegram_listener import TelegramAuthListener

IST = ZoneInfo("Asia/Kolkata")
CHECK_EVERY_SEC = 5 * 60       # re-check token validity every 5 min
REMINDER_HOUR = 8
REMINDER_MINUTE = 30
REMINDER_WEEKDAYS = {0, 1, 2, 3, 4}  # Mon-Fri (datetime.weekday(): Mon=0)


def log(msg):
    print(f"[{dt.datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def should_remind_now():
    now = dt.datetime.now(IST)
    if now.weekday() not in REMINDER_WEEKDAYS:
        return False
    return (now.hour, now.minute) >= (REMINDER_HOUR, REMINDER_MINUTE)


def main():
    log("fyers-auth-service starting")
    listener = TelegramAuthListener()
    threading.Thread(target=listener.poll_forever, daemon=True).start()

    reminded_date = None  # date() we already sent today's single reminder on

    if is_token_valid():
        log("Fyers token valid for today")
    else:
        log("Fyers token invalid/expired at startup - will remind once at 08:30 IST on a weekday")

    while True:
        try:
            today = dt.datetime.now(IST).date()
            if is_token_valid():
                pass
            elif reminded_date == today:
                pass  # already sent today's single reminder, stay quiet
            elif should_remind_now():
                log("Fyers token invalid at/after 08:30 IST on a weekday - sending auth reminder")
                send_auth_reminder()
                reminded_date = today
        except Exception as e:
            log(f"Loop error: {e}")
        time.sleep(CHECK_EVERY_SEC)


if __name__ == "__main__":
    main()
