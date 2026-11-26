"""
COGNEX Dashboard — Configuration
All agent paths derived from the actual GCP VM layout.
No new databases. No schema changes. Read-only access to existing agents.
"""

import os

BASE = "/home/anijay2021"

AGENTS = {
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
    "vwap": {
        "display_name": "VWAP",
        "account": "Kiran - r14592",
        "service": "vwap-agent",
        "db": f"{BASE}/vwap-agent/cognex_agent.db",
        "log": f"{BASE}/vwap-agent/logs/vwap.log",
        "strategies": ["VWAP Mean Reversion (3-tier)"],
        "broker_data": "Fyers",
        "broker_exec": "Paper",
    },
    "stocks18": {
        "display_name": "18SMA-Stocks",
        "account":      "Kiran - alerts only",
        "service":      "18sma-stocks-agent",
        "db":           None,
        "log":          f"{BASE}/18sma-stocks-agent/logs/stocks18.log",
        "strategies":   ["18 SMA close (15m) on F&O stocks -> ATM option alert"],
        "broker_data":  "Angel One",
        "broker_exec":  "Alerts",
    },
    "straddle": {
        "display_name": "Straddle Agent",
        "account":      "Kiran - Angel One",
        "service":      "straddle-agent",
        "db":           None,
        "log":          None,
        "strategies":   ["Nifty weekly/monthly straddle (Max Loss 3L)"],
        "broker_data":  "Angel One",
        "broker_exec":  "Paper",
    },
}

FYERS_TOKEN_PATH   = f"{BASE}/fyers-auth-service/config/fyers_token.json"
FYERS_CLIENT_ID    = "FX2G3F1GB9-100"

DASHBOARD_PORT     = 8000
LOG_TAIL_LINES     = 100        # Lines to send on first WebSocket connect
LOG_BROADCAST_INTERVAL = 1.0   # Seconds between log poll cycles
DB_REFRESH_INTERVAL    = 5.0   # Seconds between DB snapshot broadcasts
