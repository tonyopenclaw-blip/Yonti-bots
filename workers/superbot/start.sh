#!/bin/bash
export KALSHI_ACCESS_KEY=f085af89-0df7-44e2-9bb3-4af0435cbfda
cd /home/ubuntu/.openclaw/workspace/workers/superbot
python3 superbot.py >> logs/superbot.log 2>&1
