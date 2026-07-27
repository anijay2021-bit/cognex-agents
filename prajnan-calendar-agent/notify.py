"""
Self-contained Telegram notifier for prajnan-calendar-agent.
Deliberately has zero cross-agent imports (this agent does not depend on
prajnan-agent's core/notify packages) so it can run standalone.
"""
import requests
from loguru import logger
from config.settings import settings


def send_telegram_message(message: str, parse_mode: str = None) -> bool:
    token = settings.telegram_bot_token
    chat_id = settings.telegram_chat_id
    if not token or not chat_id:
        logger.warning("Telegram not configured — skipping message")
        return False
    try:
        payload = {"chat_id": chat_id, "text": message}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json=payload,
            timeout=10,
        )
        if r.status_code != 200:
            logger.warning(f"Telegram send failed: {r.status_code} {r.text}")
            return False
        return True
    except Exception as e:
        logger.warning(f"Telegram send error: {e}")
        return False
