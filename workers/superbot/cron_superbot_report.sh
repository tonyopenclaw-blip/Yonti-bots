#!/bin/bash
# cron_superbot_report.sh - Post Superbot paper trading report to Discord
# Runs every 15 min after Kalshi series closes

WORKDIR="/home/ubuntu/.openclaw/workspace/workers/superbot"
LAST_SUMMARY_FILE="/home/ubuntu/.openclaw/workspace/workers/superbot/.last_paper_summary"
FORCE=false

if [ "$1" == "--force" ]; then
    FORCE=true
fi

cd "$WORKDIR" || exit 1

# Check if report.json exists
if [ ! -f "report.json" ]; then
    echo "No report.json found, skipping."
    exit 0
fi

# Run paper report script
REPORT=$(python3 paper_report.py 2>&1)
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo "Error running paper report: $REPORT"
    exit 1
fi

# Create summary of current state (balance + trade count)
CURRENT_SUMMARY=$(python3 -c "
import json
with open('report.json') as f:
    d = json.load(f)
print(f\"{d['ending_balance']:.2f}:{d['total_trades']}:{d['total_pnl']:.4f}\")
" 2>/dev/null)

if [ -z "$CURRENT_SUMMARY" ]; then
    echo "Could not parse report.json"
    exit 1
fi

# Always post - Tony wants updates every 15 min
echo "$CURRENT_SUMMARY" > "$LAST_SUMMARY_FILE"
echo "Posting to Discord..."
python3 paper_report.py --discord 2>&1
echo "Done."