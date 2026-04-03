#!/bin/bash
#
# OpenClaw Gateway Watchdog
# Monitors the gateway process, logs crashes with diagnostics, and restarts
#

LOG_DIR="/home/ubuntu/.openclaw/logs"
CRASH_LOG="$LOG_DIR/gateway_crashes.log"
GATEWAY_LOG="/tmp/openclaw/openclaw-$(date +%Y-%m-%d).log"
PID_FILE="/tmp/openclaw_gateway.pid"
LAST_STATE_FILE="$LOG_DIR/last_state.json"

# Ensure log directory exists
mkdir -p "$LOG_DIR"

# Get current gateway status
get_gateway_info() {
    local pid=""
    local mem_mb=""
    local cpu=""
    local status="NOT_RUNNING"

    # Try to find the gateway process
    if pgrep -f "openclaw.*gateway" > /dev/null 2>&1; then
        pid=$(pgrep -f "openclaw.*gateway" | head -1)
        if [ -n "$pid" ] && [ -f "/proc/$pid/status" ]; then
            # Get memory in MB (VmRSS)
            mem_mb=$(awk '/VmRSS/ {printf "%.1f", $2/1024}' /proc/$pid/status 2>/dev/null || echo "unknown")
            # Get CPU (needs a moment to sample)
            cpu=$(top -bn1 -p "$pid" 2>/dev/null | awkNR==8 | awk '{print $9}' || echo "unknown")
            status="RUNNING"
        fi
    fi

    echo "$pid|$mem_mb|$cpu|$status"
}

# Check if gateway is healthy via RPC probe
check_gateway_health() {
    local result
    result=$(curl -s --max-time 3 http://127.0.0.1:18789 2>/dev/null || echo "FAIL")
    if [ "$result" != "FAIL" ]; then
        echo "HEALTHY"
    else
        echo "UNHEALTHY"
    fi
}

# Log a crash/restart event
log_event() {
    local event_type="$1"
    local message="$2"
    local timestamp
    timestamp=$(date '+%Y-%m-%d %H:%M:%S %Z')

    echo "[$timestamp] [$event_type] $message" >> "$CRASH_LOG"
    chmod 644 "$CRASH_LOG" 2>/dev/null
}

# Capture last N lines of gateway log
capture_log_tail() {
    local lines="${1:-30}"
    if [ -f "$GATEWAY_LOG" ]; then
        echo "=== Last $lines lines of gateway log ==="
        tail -n "$lines" "$GATEWAY_LOG" 2>/dev/null
    else
        echo "No gateway log found at $GATEWAY_LOG"
    fi
}

# Get system resource info
get_system_info() {
    echo "=== System Resources at $(date '+%Y-%m-%d %H:%M:%S') ==="
    echo "Load: $(cat /proc/loadavg)"
    echo "Memory: $(free -h | grep Mem)"
    echo "Disk: $(df -h / | tail -1)"
    echo "Uptime: $(uptime -p 2>/dev/null || uptime)"
}

# === MAIN ===
main() {
    local info
    local pid mem cpu status
    local health
    local restart_count=0
    local consecutive_failures=0

    # Read last state
    if [ -f "$LAST_STATE_FILE" ]; then
        restart_count=$(grep restart_count "$LAST_STATE_FILE" 2>/dev/null | cut -d'"' -f4 || echo "0")
    fi

    info=$(get_gateway_info)
    pid=$(echo "$info" | cut -d'|' -f1)
    mem=$(echo "$info" | cut -d'|' -f2)
    cpu=$(echo "$info" | cut -d'|' -f3)
    status=$(echo "$info" | cut -d'|' -f4)

    # Check health
    if [ "$status" = "RUNNING" ]; then
        health=$(check_gateway_health)
    else
        health="NOT_RUNNING"
    fi

    if [ "$status" != "RUNNING" ] || [ "$health" = "UNHEALTHY" ]; then
        consecutive_failures=$((consecutive_failures + 1))

        log_event "CRASH_DETECTED" "Gateway not running or unhealthy. PID=$pid, Status=$status, Health=$health"

        # Capture diagnostics before restart
        echo "" >> "$CRASH_LOG"
        echo "=== DIAGNOSTICS at $(date '+%Y-%m-%d %H:%M:%S') ===" >> "$CRASH_LOG"
        get_system_info >> "$CRASH_LOG" 2>&1

        # Check for OOM kills
        echo "=== dmesg OOM check ===" >> "$CRASH_LOG"
        dmesg 2>/dev/null | grep -i "oom\|kill\|memory" | tail -10 >> "$CRASH_LOG" || echo "No OOM messages in dmesg" >> "$CRASH_LOG"

        # Check recent systemd journal for openclaw
        echo "=== journalctl recent ===" >> "$CRASH_LOG"
        journalctl -xe --no-pager -n 20 2>/dev/null | grep -i "openclaw\|sigterm\|sigkill\|exit" | tail -10 >> "$CRASH_LOG" || echo "No relevant journal entries" >> "$CRASH_LOG"

        # Capture last lines of gateway log
        echo "=== Recent gateway log ===" >> "$CRASH_LOG"
        capture_log_tail 50 >> "$CRASH_LOG" 2>&1
        echo "" >> "$CRASH_LOG"

        # Attempt restart
        log_event "RESTART_ATTEMPT" "Attempting to restart openclaw gateway..."

        systemctl --user restart openclaw-gateway 2>/dev/null || \
            sudo systemctl restart openclaw-gateway 2>/dev/null || \
            openclaw gateway start 2>/dev/null

        sleep 5

        # Check if restart succeeded
        info=$(get_gateway_info)
        pid=$(echo "$info" | cut -d'|' -f1)
        status=$(echo "$info" | cut -d'|' -f4)

        if [ "$status" = "RUNNING" ]; then
            restart_count=$((restart_count + 1))
            log_event "RESTART_SUCCESS" "Gateway restarted. New PID=$pid. Total restarts=$restart_count"
            consecutive_failures=0
        else
            log_event "RESTART_FAILED" "Gateway still not running after restart attempt."
        fi
    else
        # Gateway healthy - log periodic heartbeat (every 10th check = ~10 min with 1-min cron)
        consecutive_failures=0
        if [ $((RANDOM % 10)) -eq 0 ]; then
            log_event "HEARTBEAT" "Gateway healthy. PID=$pid, Mem=${mem}MB, CPU=${cpu}%, Uptime=$(uptime -p 2>/dev/null || uptime)"
        fi
    fi

    # Save state
    cat > "$LAST_STATE_FILE" << EOF
{
  "last_check": "$(date -Iseconds)",
  "pid": "$pid",
  "status": "$status",
  "health": "$health",
  "memory_mb": "$mem",
  "cpu": "$cpu",
  "restart_count": $restart_count,
  "consecutive_failures": $consecutive_failures
}
EOF

    # Periodic full log capture (every hour-ish, random offset to spread load)
    if [ $((RANDOM % 60)) -eq 0 ]; then
        capture_log_tail 100 >> "$CRASH_LOG" 2>&1
    fi
}

main "$@"
