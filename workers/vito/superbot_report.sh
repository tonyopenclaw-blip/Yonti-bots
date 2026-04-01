#!/bin/bash
# Superbot Paper Report - Posts to Discord via webhook

WEBHOOK_URL="https://discord.com/api/webhooks/1486066262122430684/mLKWVlGJRyADWEnpDgx3n4QcI1B-JhAnDLyBHKwsK-BSmeo5lal5MYrrY_QiuOBqiNLy"

TIMESTAMP=$(date '+%Y-%m-%d %H:%M UTC')

REPORT="📊 **SUPERBOT PAPER REPORT** (Kelly Mode)
━━━━━━━━━━━━━━━━━━━━━━
💰 Balance: $100.00 | Paper
📈 Trades: 0 | W: 0 L: 0 | WR: 0%
💵 Total P&L: $+0.00
🔢 Streak: 0
📌 Open: 0
━━━━━━━━━━━━━━━━━━━━━━"

# Use printf for proper JSON escaping
PAYLOAD=$(printf '{"content": %s}' "$(echo "$REPORT" | jq -Rs .)")

curl -s -H "Content-Type: application/json" \
    -d "$PAYLOAD" \
    "$WEBHOOK_URL"

echo "Superbot report posted at $(date)"
