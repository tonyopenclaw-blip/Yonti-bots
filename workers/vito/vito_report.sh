#!/bin/bash
# Uncle Vito's Betting Report - Posts to Discord via webhook

WEBHOOK_URL="https://discord.com/api/webhooks/1486066262122430684/mLKWVlGJRyADWEnpDgx3n4QcI1B-JhAnDLyBHKwsK-BSmeo5lal5MYrrY_QiuOBqiNLy"

cd /home/ubuntu/.openclaw/workspace/workers/uncle_vito

# Generate the report
REPORT=$(python3 run.py 2>/dev/null)

# Post to Discord
PAYLOAD=$(printf '{"content": %s}' "$(echo "$REPORT" | jq -Rs .)")

curl -s -H "Content-Type: application/json" \
    -d "$PAYLOAD" \
    "$WEBHOOK_URL"

echo "Vito report posted at $(date)"
