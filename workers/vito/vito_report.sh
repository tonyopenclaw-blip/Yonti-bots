#!/bin/bash
# Vito's Betting Report - Posts to Discord via webhook

WEBHOOK_URL="https://discord.com/api/webhooks/1486066262122430684/mLKWVlGJRyADWEnpDgx3n4QcI1B-JhAnDLyBHKwsK-BSmeo5lal5MYrrY_QiuOBqiNLy"

TIMESTAMP=$(date '+%Y-%m-%d %H:%M UTC')

REPORT="🍝 **UNCLE VITO'S BETTING REPORT** 🍝
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📅 Generated: $TIMESTAMP

⚠️ *Report regenerating - full picks coming soon*

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

PAYLOAD=$(printf '{"content": %s}' "$(echo "$REPORT" | jq -Rs .)")

curl -s -H "Content-Type: application/json" \
    -d "$PAYLOAD" \
    "$WEBHOOK_URL"

echo "Vito report posted at $(date)"
