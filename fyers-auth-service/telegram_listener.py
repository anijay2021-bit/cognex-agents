"""
Minimal Telegram command listener for fyers-auth-service.

Handles exactly one thing (unlike prajnan-agent's full STATUS/TRADES/PAUSE/
STOP command set, none of which belongs here): a human pasting the Fyers
OAuth redirect URL back after clicking the login link from send_auth_reminder().
Accepts either:
  FYERS_AUTH https://trade.fyers.in/...&auth_code=...
or the raw pasted URL on its own (starts with https:// and contains auth_code).

Polling pattern (getUpdates + offset) copied from prajnan-agent's
notify/telegram_commands.py / main.py _run_telegram_listener, minus every
command unrelated to auth.
"""
import time

import requests
from loguru import logger

from config.settings import settings
from fyers_auto_auth import complete_auth_from_url


class TelegramAuthListener:
    def __init__(self):
        self.base_url = f"https://api.telegram.org/bot{settings.telegram_bot_token}"
        self.last_update_id = 0

    def _send(self, chat_id, text):
        try:
            requests.post(f"{self.base_url}/sendMessage",
                           json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=10)
        except Exception:
            pass

    def _cmd_fyers_auth(self, chat_id, redirect_url):
        try:
            ok = complete_auth_from_url(redirect_url)
            if ok:
                self._send(chat_id, "✅ Fyers token refreshed successfully!\nAll COGNEX agents are now live.")
            else:
                self._send(chat_id, "❌ Fyers auth failed\nPlease try again with a fresh url.")
        except Exception as e:
            logger.error(f"Auth cmd error: {e}")

    def handle_message(self, raw_text, chat_id):
        text = raw_text.strip()
        upper = text.upper()
        if upper.startswith("FYERS_AUTH"):
            url = text[10:].strip().strip("[] ")
            self._cmd_fyers_auth(chat_id, url)
        elif text.startswith("https://") and "auth_code" in text:
            self._cmd_fyers_auth(chat_id, text)
        elif upper in ("STATUS", "/STATUS", "HELP", "/HELP", "/START"):
            self._send(chat_id,
                       "\U0001f511 <b>Fyers Auth Service</b>\n"
                       "Send the Fyers login redirect URL (or FYERS_AUTH [url]) "
                       "here after logging in to refresh the shared token.")

    def poll_forever(self):
        logger.info("Telegram auth listener started")
        while True:
            try:
                r = requests.get(f"{self.base_url}/getUpdates",
                                  params={"offset": self.last_update_id, "timeout": 25}, timeout=30).json()
                for update in r.get("result", []):
                    self.last_update_id = update["update_id"] + 1
                    if "message" in update and "text" in update["message"]:
                        raw_text = update["message"]["text"]
                        chat_id = update["message"]["chat"]["id"]
                        self.handle_message(raw_text, chat_id)
            except Exception as e:
                logger.debug(f"Telegram listener error: {e}")
                time.sleep(3)
