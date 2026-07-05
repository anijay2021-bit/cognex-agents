import sys, os
sys.path.insert(0, "/home/anijay2021/prajnan-agent")
from datetime import datetime
from brokers.fyers_connector import fyers_connector
from strategies.rsi2_scanner import rsi2_scanner
import pandas as pd

fyers_connector.connect()
if fyers_connector._connected:
    df = rsi2_scanner._fetch_nifty_candles()
    if df is not None:
        close = df["close"].values.astype(float)
        rsi2 = rsi2_scanner._calculate_rsi2(close)
        df["rsi2"] = rsi2
        # Look for 11:25 signals (05:55 UTC)
        target_times = ["05:15", "05:20", "05:50", "05:55", "06:00"]
        print("--- FORENSIC RSI SCAN ---")
        for t in target_times:
            row = df[df["timestamp"].dt.strftime("%H:%M") == t]
            if not row.empty:
                print(f"Time: {t} IST (Approx) | Nifty: {row['close'].values[0]:.2f} | RSI2: {row['rsi2'].values[0]:.2f}")
