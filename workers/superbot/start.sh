#!/bin/bash
export KALSHI_ACCESS_KEY=e275fa0a-90e0-4eaa-9fb1-d25c9f8ed804
cd /home/ubuntu/.openclaw/workspace/workers/superbot
python3 superbot.py >> logs/superbot.log 2>&1
