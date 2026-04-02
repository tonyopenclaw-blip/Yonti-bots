#!/bin/bash
# cron_vito_report.sh - Run Uncle Vito report and only send to Discord if content changed
# Uncle Vito - every hour 8am to 9pm
# 0 8,9,10,11,12,13,14,15,16,17,18,19,20,21 * * * /home/ubuntu/.openclaw/workspace/workers/uncle_vito/cron_vito_report.sh >> /home/ubuntu/.openclaw/workspace/workers/uncle_vito/vito_cron.log 2>&1

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
