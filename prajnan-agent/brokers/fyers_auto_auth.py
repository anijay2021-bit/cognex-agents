import json, requests, pyotp, sys, os
from datetime import date
from pathlib import Path
from loguru import logger
PROJECT_ROOT = "/home/anijay2021/prajnan-agent"
if PROJECT_ROOT not in sys.path: sys.path.insert(0, PROJECT_ROOT)
from config.settings import settings
def is_token_valid() -> bool:
    token_file = Path(f"{PROJECT_ROOT}/config/fyers_token.json")
    if not token_file.exists(): return False
    try:
        with open(token_file, "r") as f:
            data = json.load(f)
            return data.get("date") == str(date.today())
    except: return False
def send_auth_reminder():
    try:
        from fyers_apiv3 import fyersModel
        session = fyersModel.SessionModel(client_id=settings.fyers_client_id, secret_key=settings.fyers_secret_key, redirect_uri=settings.fyers_redirect_uri, response_type="code", grant_type="authorization_code")
        auth_url = session.generate_authcode()
        msg = f"?? <b>Fyers Action Required</b>\n?????????????????????\nPlease login and paste URL back:\n\n<a href='{auth_url}'>Click here to Login</a>\n\nFormat: <code>FYERS_AUTH [url]</code>"
        requests.post(f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage", json={"chat_id": settings.telegram_chat_id, "text": msg, "parse_mode": "HTML"}, timeout=10)
    except Exception as e: logger.error(f"Reminder error: {e}")
def refresh_fyers_token(): send_auth_reminder(); return False
def complete_auth_from_url(url: str) -> bool:
    try:
        url = url.strip("[] ")
        auth_code = url.split("auth_code=")[1].split("&")[0]
        from fyers_apiv3 import fyersModel
        session = fyersModel.SessionModel(client_id=settings.fyers_client_id, secret_key=settings.fyers_secret_key, redirect_uri=settings.fyers_redirect_uri, response_type="code", grant_type="authorization_code")
        session.set_token(auth_code)
        # UPDATED: Use generate_token based on library inspection
        response = session.generate_token()
        if response.get("s") == "ok":
            token = response.get("access_token")
            with open(f"{PROJECT_ROOT}/config/fyers_token.json", "w") as f: json.dump({"token": token, "date": str(date.today())}, f)
            return True
        else:
            logger.error(f"Fyers Access Token Error: {response}")
            return False
    except Exception as e: logger.error(f"Auth completion error: {e}"); return False
if __name__ == "__main__": refresh_fyers_token()
