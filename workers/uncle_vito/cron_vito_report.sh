#!/bin/bash
# cron_vito_report.sh - Run Uncle Vito report and only send to Discord if content changed
# Usage: ./cron_vito_report.sh [--force]

WORKDIR="/home/ubuntu/.openclaw/workspace/workers/uncle_vito"
LAST_REPORT_FILE="/home/ubuntu/.openclaw/workspace/workers/uncle_vito/last_report.txt"
FORCE=false

if [ "$1" == "--force" ]; then
    FORCE=true
fi

cd "$WORKDIR" || exit 1

# Run the report and capture output
REPORT=$(python3 run.py 2>&1)
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo "Error running vito report: $REPORT"
    exit 1
fi

# Check if content changed
if [ "$FORCE" == "true" ]; then
    echo "$REPORT" > "$LAST_REPORT_FILE"
    echo "Forcing Discord send..."
    python3 run.py --discord --channel "uncle-vito" 2>&1
    exit 0
fi

# Compare with last report
if [ -f "$LAST_REPORT_FILE" ]; then
    LAST_REPORT=$(cat "$LAST_REPORT_FILE")
    if [ "$REPORT" == "$LAST_REPORT" ]; then
        echo "No change in report, skipping Discord send."
        exit 0
    fi
fi

# Content changed or first run - send to Discord
echo "$REPORT" > "$LAST_REPORT_FILE"
echo "Report changed, sending to Discord..."
python3 run.py --discord --channel "uncle-vito" 2>&1
