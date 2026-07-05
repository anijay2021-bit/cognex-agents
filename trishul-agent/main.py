import json
import math
import requests
from datetime import datetime
import pytz
import sys
import os
sys.path.insert(0, '/home/anijay2021/trishul-agent')

from strategies.signal_engine import get_signals
from brokers.angelone_orders import place_options_order
from config.settings import CAPITAL, RISK_PER_TRADE_PCT, MAX_DAILY_LOSS, TRADING_MODE

IST = pytz.timezone('Asia/Kolkata')
daily_loss = 0

def send_telegram(msg):
    try:
        with open('/home/anijay2021/trishul-agent/config/telegram_config.json') as f:
            cfg = json.load(f)
        url = f"https://api.telegram.org/bot{cfg['bot_token']}/sendMessage"
        requests.post(url, json={"chat_id": cfg['chat_id'], "text": msg})
        print(f"Telegram sent: {msg[:50]}")
    except Exception as e:
        print(f"Telegram error: {e}")

def get_atm_strike(spot):
    return round(spot / 50) * 50

def calculate_qty(entry_premium, stop_premium):
    risk_amount   = CAPITAL * RISK_PER_TRADE_PCT
    risk_per_unit = max(entry_premium - stop_premium, 10)
    raw_qty       = math.floor(risk_amount / risk_per_unit)
    lots          = max(1, math.floor(raw_qty / 65))
    return lots * 65

def run_trishul():
    global daily_loss
    now = datetime.now(IST)
    print(f"\n[{now.strftime('%H:%M:%S')}] Trishul scanning...")

    if daily_loss >= MAX_DAILY_LOSS:
        print(f"Daily loss limit hit: {daily_loss}. No trades today.")
        return

    signal, spot, rsi2 = get_signals()

    if signal is None:
        print(f"No signal. Spot: {spot:.0f} RSI2: {rsi2:.1f}")
        return

    atm    = get_atm_strike(spot)
    est_entry_premium = 85
    est_stop_premium  = 45
    qty    = calculate_qty(est_entry_premium, est_stop_premium)
    max_loss = (est_entry_premium - est_stop_premium) * qty

    msg = (
        f"🎯 TRISHUL SIGNAL\n"
        f"Mode: {TRADING_MODE}\n"
        f"Signal: {signal}\n"
        f"Spot: {spot:.0f}\n"
        f"ATM Strike: {atm}\n"
        f"RSI2: {rsi2:.1f}\n"
        f"Qty: {qty}\n"
        f"Max Risk: Rs {max_loss:.0f}\n"
        f"Time: {now.strftime('%H:%M:%S')} IST"
    )
    print(msg)
    send_telegram(msg)

    trading_symbol = f"NIFTY{now.strftime('%y%-m%d')}{atm}{signal}"
    result = place_options_order(trading_symbol, qty)
    print(f"Order result: {result}")

if __name__ == "__main__":
    from apscheduler.schedulers.blocking import BlockingScheduler

    send_telegram("🚀 TRISHUL Agent Started | Mode: PAPER | Scanning every 15 mins")

    scheduler = BlockingScheduler(timezone=IST)
    scheduler.add_job(
        run_trishul,
        'cron',
        day_of_week='mon-fri',
        hour='9-15',
        minute='2,17,32,47'
    )

    print("✅ Trishul scheduler running...")
    scheduler.start()
