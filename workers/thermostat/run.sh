#!/bin/bash
# run.sh - Run Thermostat weather arbitrage bot

cd "$(dirname "$0")"

echo "Starting Thermostat - Weather Forecast Arbitrage Bot"
echo "====================================================="

# Check Python version
python3 --version

# Create data directories
mkdir -p data logs

# Initialize data files if they don't exist
if [ ! -f data/thermostat_trades.json ]; then
    echo '{"trades": [], "stats": {}}' > data/thermostat_trades.json
    echo "{}" > data/thermostat_stats.json
    echo "Initialized data files"
fi

# Run the bot
python3 thermostat.py
