#!/bin/bash
export KALSHI_ACCESS_KEY=12920c50-132b-4237-9575-7d5958a74830
cd /home/ubuntu/.openclaw/workspace/workers/superbot
python3 superbot.py >> logs/superbot.log 2>&1
