"""
Standalone Fyers auth module for fyers-auth-service.

Extracted from prajnan-agent/brokers/fyers_auto_auth.py, unchanged in behavior:
- is_token_valid(): true only if fyers_token.json exists and its "date" == today.
- send_auth_reminder(): posts a Telegram message with a fresh Fyers OAuth login
  link. The human logs in, then pastes the redirect URL back to the bot.
- complete_auth_from_url(url): parses the auth_code out of a pasted redirect
  URL, exchanges it for an access token via fyers_apiv3, and writes
  config/fyers_token.json -- the single token file every COGNEX agent reads.
- refresh_fyers_token(): kept for compatibility with fix_auth.py-style manual
  triggers; there is no fully unattended refresh (Fyers requires a human
  login), so this just (re)sends the reminder.
"""
import json
import sys
from datetime import date
from pathlib import Path

from loguru import logger

PROJECT_ROOT = str(Path(__file__).parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from config.settings import settings


def is_token_valid() -> bool:
    token_file = Path(f"{PROJECT_ROOT}/config/fyers_token.json")
    if not token_file.exists():
        return False
    try:
        with open(token_file, "r") as f:
            data = json.load(f)
            return data.get("date") == str(date.today())
    except Exception:
        return False


def send_auth_reminder():
    try:
        import requests
        from fyers_apiv3 import fyersModel
        session = fyersModel.SessionModel(
            client_id=settings.fyers_client_id,
            secret_key=settings.fyers_secret_key,
            redirect_uri=settings.fyers_redirect_uri,
            response_type="code",
            grant_type="authorization_code",
        )
        auth_url = session.generate_authcode()
        msg = (
            f"\U0001f511 <b>Fyers Action Required</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Please login and paste URL back:\n\n"
            f"<a href='{auth_url}'>Click here to Login</a>\n\n"
            f"Format: <code>FYERS_AUTH [url]</code>"
        )
        requests.post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
            json={"chat_id": settings.telegram_chat_id, "text": msg, "parse_mode": "HTML"},
            timeout=10)
    except Exception as e:
        logger.error(f"Reminder error: {e}")


def refresh_fyers_token():
    send_auth_reminder()
    return False


def complete_auth_from_url(url: str) -> bool:
    try:
        url = url.strip("[] ")
        auth_code = url.split("auth_code=")[1].split("&")[0]
        from fyers_apiv3 import fyersModel
        session = fyersModel.SessionModel(
            client_id=settings.fyers_client_id,
            secret_key=settings.fyers_secret_key,
            redirect_uri=settings.fyers_redirect_uri,
            response_type="code",
            grant_type="authorization_code",
        )
        session.set_token(auth_code)
        response = session.generate_token()
        if response.get("s") == "ok":
            token = response.get("access_token")
            with open(f"{PROJECT_ROOT}/config/fyers_token.json", "w") as f:
                json.dump({"token": token, "date": str(date.today())}, f)
            return True
        else:
            logger.error(f"Fyers Access Token Error: {response}")
            return False
    except Exception as e:
        logger.error(f"Auth completion error: {e}")
        return False


if __name__ == "__main__":
    refresh_fyers_token()
