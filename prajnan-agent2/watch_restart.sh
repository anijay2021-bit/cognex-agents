#!/bin/bash
DIR=/home/anijay2021/cognex-agent2
LOG=$DIR/logs/rsi2_scanner_vix_removed.log
cd $DIR
PREV=$(md5sum main.py strategies/rsi2_scanner.py risk/risk_guard.py core/order_executor.py 2>/dev/null | md5sum | cut -d' ' -f1)
echo "$(date): Watcher started"
while true; do
    sleep 10
    CUR=$(md5sum main.py strategies/rsi2_scanner.py risk/risk_guard.py core/order_executor.py 2>/dev/null | md5sum | cut -d' ' -f1)
    if [ "$CUR" != "$PREV" ]; then
        echo "$(date): Change detected — restarting agent"
        pkill -f "python3 main.py" 2>/dev/null
        sleep 2
        nohup ./venv/bin/python3 main.py >> $LOG 2>&1 &
        echo "$(date): Agent restarted PID=$!"
        PREV=$CUR
    fi
done
