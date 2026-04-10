#!/bin/bash
cd /home/ubuntu/.openclaw/workspace/workers/superbot
pkill -f "python3 superbot.py" 2>/dev/null
sleep 1
KALSHI_ACCESS_KEY=12920c50-132b-4237-9575-7d5958a74830 nohup python3 superbot.py > superbot_live.log 2>&1 &
echo "Started PID: $!"
