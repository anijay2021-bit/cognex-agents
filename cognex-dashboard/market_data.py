"""
COGNEX Dashboard — Fyers LTP Market Data
Reads the existing Fyers access token from prajnan-agent's config.
Polls Fyers REST API every 5 seconds for Nifty spot + BankNifty + VIX.
Broadcasts via WebSocket → shows up live in signal monitor.
"""

import asyncio
import os
import json
import requests
from datetime import datetime

BASE = "/home/anijay2021"
CLIENT_ID = "FX2G3F1GB9-100"

# Possible token file locations
TOKEN_PATHS = [
    f"{BASE}/prajnan-agent/.env",
    f"{BASE}/prajnan-agent/config/.env",
    f"{BASE}/prajnan-agent/fyers_access_token.txt",
    f"{BASE}/prajnan-agent/config/fyers_token.json",
    f"{BASE}/prajnan-agent/config/fyers_token.txt",
]

SYMBOLS = "NSE:NIFTY50-INDEX,NSE:NIFTYBANK-INDEX,NSE:INDIA VIX"
QUOTES_URL = "https://api-t1.fyers.in/data/quotes"
POLL_INTERVAL = 5  # seconds


def _read_token() -> str | None:
    """Try all known token file locations and formats."""
    for path in TOKEN_PATHS:
        if not os.path.exists(path):
            continue
        try:
            content = open(path).read().strip()

            # JSON format: {"access_token": "eyJ..."}
            if content.startswith("{"):
                data = json.loads(content)
                for key in ("access_token", "AccessToken", "token", "fyers_token"):
                    if key in data:
                        return data[key]

            # .env format: FYERS_ACCESS_TOKEN=eyJ...
            if "=" in content:
                for line in content.splitlines():
                    line = line.strip()
                    for key in ("FYERS_ACCESS_TOKEN", "ACCESS_TOKEN", "FYERS_TOKEN"):
                        if line.startswith(key + "="):
                            val = line.split("=", 1)[1].strip().strip('"').strip("'")
                            if val and len(val) > 20:
                                return val

            # Plain token string
            if len(content) > 20 and "\n" not in content:
                return content

        except Exception:
            continue
    return None


def _fetch_ltp(token: str) -> dict | None:
    """Call Fyers REST API and return symbol→ltp mapping."""
    try:
        headers = {"Authorization": f"{CLIENT_ID}:{token}"}
        r = requests.get(
            QUOTES_URL,
            headers=headers,
            params={"symbols": SYMBOLS},
            timeout=4,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        if data.get("s") != "ok":
            return None

        result = {}
        for item in data.get("d", []):
            sym = item.get("n", "")
            ltp = item.get("v", {}).get("lp", 0)
            if "NIFTY50" in sym:
                result["nifty"] = round(ltp, 2)
            elif "NIFTYBANK" in sym or "BANKNIFTY" in sym:
                result["banknifty"] = round(ltp, 2)
            elif "VIX" in sym:
                result["vix"] = round(ltp, 2)
        return result
    except Exception:
        return None


async def start_ltp_feed(ws_manager):
    """Background task — polls Fyers every 5 seconds and broadcasts LTP."""
    print("📡 Starting Fyers LTP feed...")
    consecutive_fails = 0

    while True:
        await asyncio.sleep(POLL_INTERVAL)

        token = _read_token()
        if not token:
            if consecutive_fails == 0:
                print("⚠️  Fyers token not found — LTP feed inactive")
            consecutive_fails += 1
            if consecutive_fails > 12:  # log every minute max
                consecutive_fails = 1
            continue

        ltp_data = _fetch_ltp(token)
        if not ltp_data:
            consecutive_fails += 1
            continue

        consecutive_fails = 0

        await ws_manager.broadcast({
            "type":      "ltp_update",
            "timestamp": datetime.now().isoformat(),
            "data":      ltp_data,
        })
