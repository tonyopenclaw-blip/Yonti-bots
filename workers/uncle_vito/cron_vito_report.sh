#!/bin/bash
# cron_vito_report.sh - Run Uncle Vito report with API key rotation
# Rotates between 2 API keys to maximize 500 calls/month each
# Runs 3x daily: 9am, 12pm, 6pm EST

WORKDIR="/home/ubuntu/.openclaw/workspace/workers/uncle_vito"
CONFIG="$WORKDIR/config.py"
LAST_KEY_FILE="$WORKDIR/.last_api_key"
FORCE=false

if [ "$1" == "--force" ]; then
    FORCE=true
fi

# Determine which key to use
if [ -f "$LAST_KEY_FILE" ]; then
    LAST_KEY=$(cat "$LAST_KEY_FILE")
    if [ "$LAST_KEY" == "5b62457b1049c4e92541d10b53b64aa3" ]; then
        CURRENT_KEY="cb42c4fe578ae32bbaf58923493d26e5"
    else
        CURRENT_KEY="5b62457b1049c4e92541d10b53b64aa3"
    fi
else
    CURRENT_KEY="5b62457b1049c4e92541d10b53b64aa3"
fi

# Update config.py with current key
sed -i "s/^ODDS_API_KEY = \".*\"/ODDS_API_KEY = \"$CURRENT_KEY\"/" "$CONFIG"
echo "$CURRENT_KEY" > "$LAST_KEY_FILE"

cd "$WORKDIR" || exit 1

# Run the report
REPORT=$(python3 run.py 2>&1)
EXIT_CODE=$?

echo "[$(date)] Using API key: ${CURRENT_KEY:0:10}..." >> "$WORKDIR/vito_cron.log"
echo "[$(date)] Report output: $REPORT" >> "$WORKDIR/vito_cron.log"

if [ $EXIT_CODE -ne 0 ]; then
    echo "Error running vito report: $REPORT"
    exit 1
fi

# Send to Discord
python3 run.py --discord --channel uncle-vito 2>&1

echo "[$(date)] Done." >> "$WORKDIR/vito_cron.log"
