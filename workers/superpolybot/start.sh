#!/bin/bash
# start.sh - Start SuperPolybot

cd "$(dirname "$0")"

# Activate virtual environment if exists
if [ -d "../.venv" ]; then
    source ../.venv/bin/activate
fi

# Set Python path
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

# Run the bot
exec python3 superpolybot.py
