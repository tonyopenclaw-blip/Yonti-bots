#!/bin/bash
# Superbot Paper Report - Posts to Discord every 15 minutes
# Jenkins, CSO - Strategy Layer

WEBHOOK_URL="${DISCORD_WEBHOOK:-}"

REPORT="
📊 **SUPERBOT PAPER REPORT** (Kelly Mode)
━━━━━━━━━━━━━━━━━━━━━━
💰 Balance: \$100.00 | Paper
📈 Trades: 0 | W: 0 L: 0 | WR: 0%
💵 Total P&L: \$+0.00
🔢 Streak: 0
📌 Open: 0
━━━━━━━━━━━━━━━━━━━━━━
"

if [ -z "$WEBHOOK_URL" ]; then
    echo "ERROR: DISCORD_WEBHOOK not set"
    exit 1
fi

curl -s -H "Content-Type: application/json" \
    -d "{\"content\": \"$REPORT\"}" \
    "$WEBHOOK_URL"

echo "Superbot report posted at $(date)"
