"""
fyers-auth-service - standalone daily Fyers token owner for the whole COGNEX
stack (nitin-agent, 18sma-agent, prajnan-calendar-agent, cognex-dashboard all
read config/fyers_token.json from here).

Replaces the auth-refresh role that used to live inside prajnan-agent's
process (brokers/fyers_auto_auth.py + notify/telegram_commands.py FYERS_AUTH
handler + main.py's startup is_token_valid() check). Behavior is unchanged:
Fyers requires a human login once a day, so this service (1) checks token
validity, (2) sends a Telegram reminder with a login link when it's stale,
and (3) listens for the pasted-back redirect URL to complete the refresh.
"""
import datetime as dt
import threading
import time

from loguru import logger

from config.settings import settings
from fyers_auto_auth import is_token_valid, send_auth_reminder
from telegram_listener import TelegramAuthListener

CHECK_EVERY_SEC = 5 * 60       # re-check token validity every 5 min
REMINDER_COOLDOWN_SEC = 20 * 60  # don't re-nag more than once per 20 min


def log(msg):
    print(f"[{dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def main():
    log("fyers-auth-service starting")
    listener = TelegramAuthListener()
    threading.Thread(target=listener.poll_forever, daemon=True).start()

    last_reminder_ts = 0.0
    if not is_token_valid():
        log("Fyers token invalid/expired at startup - sending auth reminder")
        send_auth_reminder()
        last_reminder_ts = time.time()
    else:
        log("Fyers token valid for today")

    while True:
        try:
            if is_token_valid():
                if last_reminder_ts:
                    log("Fyers token now valid")
                last_reminder_ts = 0.0
            else:
                now = time.time()
                if now - last_reminder_ts >= REMINDER_COOLDOWN_SEC:
                    log("Fyers token invalid - sending auth reminder")
                    send_auth_reminder()
                    last_reminder_ts = now
        except Exception as e:
            log(f"Loop error: {e}")
        time.sleep(CHECK_EVERY_SEC)


if __name__ == "__main__":
    main()
