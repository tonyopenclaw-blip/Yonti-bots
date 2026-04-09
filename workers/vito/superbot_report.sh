#!/bin/bash

# Discord webhook URL - replace with actual webhook
WEBHOOK_URL="YOUR_DISCORD_WEBHOOK_URL_HERE"

MESSAGE="📊 SUPERBOT PAPER REPORT (Kelly Mode)
━━━━━━━━━━━━━━━━━━━━━━
💰 Balance: \$100.00 | Paper
📈 Trades: 0 | W: 0 L: 0 | WR: 0%
💵 Total P&L: $+0.00
🔢 Streak: 0
📌 Open: 0
━━━━━━━━━━━━━━━━━━━━━━"

curl -s -H "Content-Type: application/json" \
     -d "{\"content\": \"$MESSAGE\"}" \
     "$WEBHOOK_URL"
