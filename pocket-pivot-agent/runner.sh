#!/bin/bash
# Pocket Pivot runner - scans every INTERVAL_SEC during IST market window, Mon-Fri.
# Window/interval come from config.env (dashboard-managed).
BASE=/home/anijay2021/pocket-pivot-agent
set -a; source "$BASE/.env"; set +a
while true; do
  SCAN_FROM="09:15"; NO_SCAN_AFTER="15:29"; INTERVAL_SEC=60
  [ -f "$BASE/config.env" ] && source "$BASE/config.env"
  dow=$(date -u +%u)
  ist=$(date -u -d '+330 minutes' +%H%M)
  from=${SCAN_FROM/:/}; till=${NO_SCAN_AFTER/:/}
  if (( dow <= 5 )) && (( 10#$ist >= 10#$from )) && (( 10#$ist <= 10#$till )); then
    "$BASE/venv/bin/python" "$BASE/pocket_pivot_agent.py" >> "$BASE/logs/pocket_pivot.log" 2>&1
  fi
  sleep "$INTERVAL_SEC"
done
