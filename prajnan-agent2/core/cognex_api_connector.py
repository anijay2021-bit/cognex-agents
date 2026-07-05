"""
Cognex Cloud API Connector
Syncs trade data to Google Sheets via the deployed Apps Script Web API.
Called after every OPEN and CLOSE trade event in cognex-agent2.
"""
import requests
from loguru import logger
from config.settings import settings


COGNEX_API_URL    = settings.cognex_api_url
COGNEX_TENANT_ID  = settings.cognex_tenant_id


def sync_trade(
    strategy: str,
    symbol: str,
    action: str,       # "OPENED" or "CLOSED"
    pnl: float = 0.0,
) -> bool:
    """
    POST a trade event to the Cognex Cloud API (Google Apps Script).

    Args:
        strategy : e.g. "RSI2_SMA200" or "CALENDAR_SPREAD"
        symbol   : e.g. "NSE:NIFTY26APR22500CE"
        action   : "OPENED" or "CLOSED"
        pnl      : Profit/Loss in Rs (0.0 for OPENED events)

    Returns:
        True if the API accepted the data, False on error.
    """
    if not COGNEX_API_URL:
        logger.warning("[CognexAPI] COGNEX_API_URL not set — skipping sync")
        return False

    payload = {
        "tenant_id": COGNEX_TENANT_ID,
        "strategy":  strategy,
        "symbol":    symbol,
        "action":    action,
        "pnl":       round(pnl, 2),
    }

    try:
        response = requests.post(
            COGNEX_API_URL,
            json=payload,
            timeout=10,
            allow_redirects=True,
        )
        body = response.text.strip()

        if "Success" in body:
            logger.info(f"[CognexAPI] Synced {action} {symbol} PnL={pnl:.0f} → {body}")
            return True
        elif "Access Denied" in body:
            logger.warning(f"[CognexAPI] Access Denied — check tenant_id: {COGNEX_TENANT_ID}")
            return False
        else:
            logger.warning(f"[CognexAPI] Unexpected response: {body}")
            return False

    except requests.exceptions.Timeout:
        logger.error("[CognexAPI] Request timed out")
        return False
    except Exception as e:
        logger.error(f"[CognexAPI] Sync failed: {e}")
        return False
