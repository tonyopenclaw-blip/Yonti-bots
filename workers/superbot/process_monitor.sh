#!/bin/bash
# Auto-restart monitor for superbot and candle_watcher
# Run every 5 minutes via cron

WORKDIR="/home/ubuntu/.openclaw/workspace/workers/superbot"
LOG="$WORKDIR/process_monitor.log"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') | $1" >> "$LOG"
}

SB_PID=$(pgrep -f "python3.*superbot.py" | head -1)
CW_PID=$(pgrep -f "python3.*candle_watcher.py" | grep -v pgrep | head -1)

if [ -z "$SB_PID" ]; then
    log "SUPERBOT DOWN - restarting..."
    cd "$WORKDIR"
    nohup python3 superbot.py >> superbot_live.log 2>&1 &
    sleep 1
    NEW_PID=$(pgrep -f "python3.*superbot.py" | head -1)
    log "SUPERBOT restarted - new PID: $NEW_PID"
else
    log "SUPERBOT OK - PID: $SB_PID"
fi

if [ -z "$CW_PID" ]; then
    log "CANDLE_WATCHER DOWN - restarting..."
    cd "$WORKDIR"
    nohup python3 candle_watcher.py >> candle_watcher.log 2>&1 &
    sleep 1
    NEW_PID=$(pgrep -f "python3.*candle_watcher.py" | grep -v pgrep | head -1)
    log "CANDLE_WATCHER restarted - new PID: $NEW_PID"
else
    log "CANDLE_WATCHER OK - PID: $CW_PID"
fi
