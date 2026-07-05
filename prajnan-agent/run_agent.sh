#!/bin/bash
# Auto-restart script for COGNEX agent — called by cron at 09:10 IST (03:40 UTC)
AGENT_DIR="/home/anijay2021/prajnan-agent"
PYTHON="$AGENT_DIR/venv/bin/python3"
LOG="$AGENT_DIR/logs/agent_morning.log"

# Kill any stale process
pkill -f "venv/bin/python3 main.py" 2>/dev/null
sleep 2

# Rotate log
[ -f "$LOG" ] && mv "$LOG" "${LOG%.log}_$(date +%Y%m%d).log"

# Start fresh
cd "$AGENT_DIR"
nohup "$PYTHON" main.py > "$LOG" 2>&1 &
echo "$(date): COGNEX agent started PID $!"
