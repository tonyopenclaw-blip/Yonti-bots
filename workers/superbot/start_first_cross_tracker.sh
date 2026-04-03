#!/bin/bash
# Start the First Cross Tracker in the background
# This runs alongside Superbot/Recorder without affecting trading

cd "$(dirname "$0")"

echo "🎯 Starting First Cross Tracker..."
python3 first_cross_tracker.py >> logs/first_cross_tracker.stdout.log 2>&1 &
echo "First Cross Tracker started with PID $!"
