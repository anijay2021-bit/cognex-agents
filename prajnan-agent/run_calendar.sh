#!/bin/bash
# Nifty Calendar Spread launcher — called by cron at 09:15 IST (03:45 UTC)
cd /home/anijay2021/prajnan-agent
export PYTHONPATH=/home/anijay2021/prajnan-agent
exec /home/anijay2021/prajnan-agent/venv/bin/python3 strategies/calendar_main.py
