"""
COGNEX Dashboard — Configuration
All agent paths derived from the actual GCP VM layout.
No new databases. No schema changes. Read-only access to existing agents.
"""

import os

BASE = "/home/anijay2021"

AGENTS = {
    "prajnan_calendar": {
        "display_name": "Prajnan Calendar Agent",
        "account":      "Kiran - r14592",
        "service":      "prajnan-calendar-agent",
        "db":           None,
        "log":          f"{BASE}/prajnan-calendar-agent/logs/calendar_spread.log",
        "strategies":   ["Calendar Spread"],
        "broker_data":  "Fyers",
        "broker_exec":  "Fyers",
    },
    "nitin": {
        "display_name": "Nitin Agent",
        "account":      "Kiran - r14592",
        "service":      "nitin-agent",
        "db":           f"{BASE}/nitin-agent/cognex_agent.db",
        "log":          f"{BASE}/nitin-agent/logs/nitin.log",
        "strategies":   ["Nitin Swing (Flag/Base/DTL/VCP)"],
        "broker_data":  "Fyers",
        "broker_exec":  "Paper",
    },
    "sma18": {
        "display_name": "18SMA",
        "account":      "Kiran - r14592",
        "service":      "18sma-agent",
        "db":           f"{BASE}/18sma-agent/cognex_agent.db",
        "log":          f"{BASE}/18sma-agent/logs/18sma.log",
        "strategies":   ["18 SMA + 2-Candle Breakout"],
        "broker_data":  "Fyers",
        "broker_exec":  "Paper",
    },
    "pocketpivot": {
        "display_name": "Pocket Pivot",
        "account":      "Kiran - alerts only",
        "service":      "pocket-pivot-agent",
        "db":           None,
        "log":          f"{BASE}/pocket-pivot-agent/logs/pocket_pivot.log",
        "strategies":   ["Pocket Pivot (Chartink scan -> Telegram)"],
        "broker_data":  "Chartink",
        "broker_exec":  "Alerts",
    },
}

FYERS_TOKEN_PATH   = f"{BASE}/fyers-auth-service/config/fyers_token.json"
FYERS_CLIENT_ID    = "FX2G3F1GB9-100"

DASHBOARD_PORT     = 8000
LOG_TAIL_LINES     = 100        # Lines to send on first WebSocket connect
LOG_BROADCAST_INTERVAL = 1.0   # Seconds between log poll cycles
DB_REFRESH_INTERVAL    = 5.0   # Seconds between DB snapshot broadcasts
