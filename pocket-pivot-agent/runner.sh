#!/bin/bash
# Pocket Pivot runner - scans every 60s during NSE market hours (09:15-15:29 IST = 03:45-09:59 UTC), Mon-Fri
set -a; source /home/anijay2021/pocket-pivot-agent/.env; set +a
cd /home/anijay2021/pocket-pivot-agent
while true; do
  dow=$(date -u +%u); hm=$(date -u +%H%M)
  if (( dow <= 5 )) && (( 10#$hm >= 345 )) && (( 10#$hm <= 959 )); then
    ./venv/bin/python pocket_pivot_agent.py >> logs/pocket_pivot.log 2>&1
  fi
  sleep 60
done
