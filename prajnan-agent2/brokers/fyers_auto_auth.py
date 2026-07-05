import json
import requests
import pyotp
from datetime import date
from pathlib import Path
from loguru import logger


def is_token_valid() -> bool:
    try:
        with open("config/fyers_token.json") as f:
            data = json.load(f)
            return data.get("date") == str(date.today())
    except Exception:
        return False


def send_auth_reminder():
    try:
        import sys
        sys.path.insert(0, ".")
        from config.settings import settings
        from fyers_apiv3 import fyersModel
        session = fyersModel.SessionModel(
            client_id=settings.fyers_client_id,
            secret_key=settings.fyers_secret_key,
            redirect_uri=settings.fyers_redirect_uri,
            response_type="code",
            grant_type="authorization_code"
        )
        auth_url = session.generate_authcode()
        msg = (
            "🔐 <b>Fyers Login Required</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "Token expired. Please login:\n\n"
            f"1. Open: {auth_url}\n\n"
            "2. Login with Fyers credentials\n"
            "3. Copy full redirect URL\n"
            "4. Send here: <code>FYERS_AUTH your_url</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━"
        )
        requests.post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
            json={"chat_id": settings.telegram_chat_id, "text": msg, "parse_mode": "HTML"},
            timeout=10
        )
        logger.info("Fyers auth reminder sent")
    except Exception as e:
        logger.error(f"send_auth_reminder error: {e}")


def complete_auth_from_url(redirect_url: str) -> bool:
    try:
        import sys
        sys.path.insert(0, ".")
        from config.settings import settings
        from fyers_apiv3 import fyersModel

        if "auth_code=" not in redirect_url:
            logger.error("No auth_code in URL")
            return False

        auth_code = redirect_url.split("auth_code=")[1].split("&")[0]
        session = fyersModel.SessionModel(
            client_id=settings.fyers_client_id,
            secret_key=settings.fyers_secret_key,
            redirect_uri=settings.fyers_redirect_uri,
            response_type="code",
            grant_type="authorization_code"
        )
        session.set_token(auth_code)
        response = session.generate_token()

        if response.get("s") != "ok":
            logger.error(f"Token failed: {response}")
            return False

        token = response["access_token"]
        with open("config/fyers_token.json", "w") as f:
            json.dump({"token": token, "date": str(date.today())}, f)

        logger.success(f"Fyers token saved — {date.today()}")
        return True

    except Exception as e:
        logger.error(f"complete_auth error: {e}")
        return False


def refresh_fyers_token() -> bool:
    """
    Attempt fully automatic token refresh using TOTP + PIN.
    Falls back to sending Telegram reminder if it fails.
    """
    import sys
    sys.path.insert(0, ".")
    from config.settings import settings

    logger.info("Attempting Fyers auto token refresh...")

    try:
        from fyers_apiv3 import fyersModel

        totp_secret = settings.fyers_totp_secret
        fyers_pin   = settings.fyers_pin
        fyers_user  = "FAI97693"

        if not totp_secret or not fyers_pin:
            logger.warning("TOTP or PIN not set — sending reminder")
            send_auth_reminder()
            return False

        totp = pyotp.TOTP(totp_secret).now()
        headers = {"Content-Type": "application/json"}

        # Step 1
        r = requests.post(
            "https://api-t2.fyers.in/vagator/v2/send_login_otp_v2",
            json={"fy_id": fyers_user, "app_id": "2"},
            headers=headers, timeout=10
        )
        data = r.json()
        if data.get("s") != "ok":
            logger.warning(f"Auto-auth step1 failed: {data.get('message')} — sending reminder")
            send_auth_reminder()
            return False

        request_key = data.get("request_key", "")

        # Step 2
        r = requests.post(
            "https://api-t2.fyers.in/vagator/v2/verify_otp",
            json={"request_key": request_key, "otp": totp},
            headers=headers, timeout=10
        )
        data = r.json()
        if data.get("s") != "ok":
            logger.warning(f"Auto-auth step2 failed — sending reminder")
            send_auth_reminder()
            return False

        request_key = data.get("request_key", "")

        # Step 3
        r = requests.post(
            "https://api-t2.fyers.in/vagator/v2/verify_pin_v2",
            json={"request_key": request_key, "identity_type": "pin", "identifier": fyers_pin},
            headers=headers, timeout=10
        )
        data = r.json()
        if data.get("s") != "ok":
            logger.warning(f"Auto-auth step3 failed — sending reminder")
            send_auth_reminder()
            return False

        access_token = data.get("data", {}).get("access_token", "")

        # Step 4
        app_id = settings.fyers_client_id.split("-")[0]
        r = requests.post(
            "https://api-t2.fyers.in/api/v3/token",
            json={
                "fyers_id": fyers_user, "app_id": app_id,
                "redirect_uri": settings.fyers_redirect_uri,
                "appType": "100", "code_challenge": "",
                "state": "None", "scope": "", "nonce": "",
                "response_type": "code", "create_cookie": True
            },
            headers={**headers, "Authorization": f"Bearer {access_token}"},
            timeout=10
        )
        data = r.json()
        if data.get("s") != "ok":
            logger.warning(f"Auto-auth step4 failed — sending reminder")
            send_auth_reminder()
            return False

        url = data.get("Url", "")
        if "auth_code=" not in url:
            send_auth_reminder()
            return False

        auth_code = url.split("auth_code=")[1].split("&")[0]

        # Step 5
        session = fyersModel.SessionModel(
            client_id=settings.fyers_client_id,
            secret_key=settings.fyers_secret_key,
            redirect_uri=settings.fyers_redirect_uri,
            response_type="code",
            grant_type="authorization_code"
        )
        session.set_token(auth_code)
        response = session.generate_token()

        if response.get("s") != "ok":
            send_auth_reminder()
            return False

        token = response["access_token"]
        with open("config/fyers_token.json", "w") as f:
            json.dump({"token": token, "date": str(date.today())}, f)

        logger.success(f"Fyers token auto-refreshed — {date.today()}")
        return True

    except Exception as e:
        logger.error(f"refresh_fyers_token error: {e}")
        send_auth_reminder()
        return False

if __name__ == "__main__":
    refresh_fyers_token()
