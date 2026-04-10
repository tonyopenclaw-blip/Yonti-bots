#!/bin/bash
cd /home/ubuntu/.openclaw/workspace/workers/superbot
pkill -f "python3 superbot.py" 2>/dev/null
sleep 1
# Use the working key (2af9792d-cadd-4067-a861-b9bff4238248) - the old key (12920c50...) has broken portfolio auth
KALSHI_ACCESS_KEY=2af9792d-cadd-4067-a861-b9bff4238248 nohup python3 superbot.py > superbot_live.log 2>&1 &
echo "Started PID: $!"
