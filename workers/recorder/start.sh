#!/bin/bash
# Quick start script for Recorder bot

cd "$(dirname "$0")"

echo "📊 Starting Recorder Bot..."
echo "   Data file: data/market_data.jsonl"
echo "   Log file: logs/recorder.log"
echo ""

python3 recorder.py
