"""
COGNEX Dashboard — Configuration
All agent paths derived from the actual GCP VM layout.
No new databases. No schema changes. Read-only access to existing agents.
"""

import os

BASE = "/home/anijay2021"

AGENTS = {
    "prajnan": {
        "display_name": "Prajñān",
        "account":      "Kiran — r14592",
        "service":      "prajnan-agent",
        "db":           f"{BASE}/prajnan-agent/cognex_agent.db",
        "log":          f"{BASE}/prajnan-agent/logs/agent.log",
        "strategies":   ["RSI2", "EMA+OBV", "Calendar Spread"],
        "broker_data":  "Fyers",
        "broker_exec":  "AngelOne",
    },
    "prajnan2": {
        "display_name": "Prajñān2",
        "account":      "Father — V12791",
        "service":      "prajnan-agent2",
        "db":           f"{BASE}/prajnan-agent2/cognex_agent.db",
        "log":          f"{BASE}/prajnan-agent2/logs/agent.log",
        "strategies":   ["RSI2"],
        "broker_data":  "AngelOne",
        "broker_exec":  "AngelOne",
    },
    "trishul": {
        "display_name": "Trishul",
        "account":      "Kiran — r14592",
        "service":      "trishul-agent",
        "db":           None,          # No SQLite — logs via systemd journal
        "log":          f"{BASE}/trishul-agent/logs/trishul.log",
        "strategies":   ["Trishul Mean Reversion"],
        "broker_data":  "Fyers",
        "broker_exec":  "AngelOne",
    },
}

FYERS_TOKEN_PATH   = f"{BASE}/prajnan-agent/config/fyers_token.json"
FYERS_CLIENT_ID    = "FX2G3F1GB9-100"

DASHBOARD_PORT     = 8000
LOG_TAIL_LINES     = 100        # Lines to send on first WebSocket connect
LOG_BROADCAST_INTERVAL = 1.0   # Seconds between log poll cycles
DB_REFRESH_INTERVAL    = 5.0   # Seconds between DB snapshot broadcasts
