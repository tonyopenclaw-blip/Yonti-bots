#!/bin/bash
cd /home/ubuntu/.openclaw/workspace/workers/superbot
pkill -f "python3.*superbot.py" 2>/dev/null
# Wait for process to fully terminate before starting new one
sleep 3
# Verify old process is dead
if pgrep -f "python3.*superbot.py" > /dev/null; then
    echo "Old process still running, waiting..."
    sleep 5
    pkill -9 -f "python3.*superbot.py" 2>/dev/null
    sleep 2
fi
# Use the working key (2af9792d-cadd-4067-a861-b9bff4238248)
KALSHI_ACCESS_KEY=2af9792d-cadd-4067-a861-b9bff4238248 nohup python3 superbot.py > superbot_live.log 2>&1 &
echo "Started PID: $!"
