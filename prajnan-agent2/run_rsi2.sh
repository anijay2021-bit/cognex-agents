#!/bin/bash
# COGNEX V2 launcher — fully independent of cognex-agent (V1)
# Runs: main.py (RSI2 + SMA200, 5-min clock-aligned)
# Called by cron at 09:15 IST (03:45 UTC) Mon-Fri

cd /home/anijay2021/cognex-agent2
export PYTHONPATH=/home/anijay2021/cognex-agent2

TOKEN="/home/anijay2021/cognex-agent2/config/fyers_token.json"

if [ -f "$TOKEN" ]; then
  nohup ./venv/bin/python3 main.py >> logs/rsi2_scanner_vix_removed.log 2>&1 &
  echo "$(date): RSI2 Scanner (V2) started — PID $!"
else
  echo "$(date): Token missing at $TOKEN. Complete Fyers login on Telegram first."
fi
