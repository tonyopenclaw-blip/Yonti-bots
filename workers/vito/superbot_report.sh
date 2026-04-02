#!/bin/bash
# Unified Paper Trading Report - Posts Superbot + Flip to Discord

WEBHOOK_URL="https://discord.com/api/webhooks/1486066262122430684/mLKWVlGJRyADWEnpDgx3n4QcI1B-JhAnDLyBHKwsK-BSmeo5lal5MYrrY_QiuOBqiNLy"

SUPERBOT_STATS="/home/ubuntu/.openclaw/workspace/workers/superbot/report.json"
FLIP_STATS="/home/ubuntu/.openclaw/workspace/workers/flip/data/flip_stats.json"
FLIP_TRADES="/home/ubuntu/.openclaw/workspace/workers/flip/data/flip_trades.json"
OUTPUT_HTML="/home/ubuntu/.openclaw/workspace/workers/unified_report.html"

# Run the Python report generator
python3 /home/ubuntu/.openclaw/workspace/workers/report.py > /dev/null 2>&1

# Read Superbot stats
if [ -f "$SUPERBOT_STATS" ]; then
    SB_BALANCE=$(jq -r '.ending_balance // 100.0' "$SUPERBOT_STATS")
    SB_TRADES=$(jq -r '.total_trades // 0' "$SUPERBOT_STATS")
    SB_WINS=$(jq -r '.winning_trades // 0' "$SUPERBOT_STATS")
    SB_LOSSES=$(jq -r '.losing_trades // 0' "$SUPERBOT_STATS")
    SB_WR=$(jq -r '.win_rate // 0' "$SUPERBOT_STATS")
    SB_PNL=$(jq -r '.total_pnl // 0' "$SUPERBOT_STATS")
    SB_OPEN=$(jq -r '.open_positions // 0' "$SUPERBOT_STATS")
else
    SB_BALANCE=100.0
    SB_TRADES=0
    SB_WINS=0
    SB_LOSSES=0
    SB_WR=0
    SB_PNL=0
    SB_OPEN=0
fi

# Read Flip stats
if [ -f "$FLIP_STATS" ]; then
    FLIP_BALANCE=$(jq -r '.balance // 100.0' "$FLIP_STATS")
    FLIP_TRADES=$(jq -r '.total_trades // 0' "$FLIP_STATS")
    FLIP_POSITIONS=$(jq -r '.total_positions // 0' "$FLIP_STATS")
    FLIP_PNL=$(jq -r '.session_pnl // 0' "$FLIP_STATS")
else
    FLIP_BALANCE=100.0
    FLIP_TRADES=0
    FLIP_POSITIONS=0
    FLIP_PNL=0
fi

# Calculate totals
TOTAL_BALANCE=$(echo "$SB_BALANCE + $FLIP_BALANCE" | bc -l)
TOTAL_START=200.0
TOTAL_PNL=$(echo "$SB_PNL + $FLIP_PNL" | bc -l)

# Format numbers
SB_BALANCE_FMT=$(printf "%.2f" "$SB_BALANCE")
FLIP_BALANCE_FMT=$(printf "%.2f" "$FLIP_BALANCE")
TOTAL_BALANCE_FMT=$(printf "%.2f" "$TOTAL_BALANCE")
TOTAL_START_FMT=$(printf "%.2f" "$TOTAL_START")
SB_PNL_FMT=$(printf "%+.2f" "$SB_PNL")
FLIP_PNL_FMT=$(printf "%+.2f" "$FLIP_PNL")
TOTAL_PNL_FMT=$(printf "%+.2f" "$TOTAL_PNL")
SB_WR_FMT=$(printf "%.0f" "$SB_WR")
FLIP_POS_FMT=$(printf "%d" "$FLIP_POSITIONS")

# Parse open positions from flip trades (last 10 by timestamp)
OPEN_POSITIONS=""
if [ -f "$FLIP_TRADES" ]; then
    # Get last 10 BUY trades with pnl=0 (open positions)
    OPEN_COUNT=0
    while IFS= read -r line; do
        if [ $OPEN_COUNT -ge 10 ]; then
            break
        fi
        ticker=$(echo "$line" | jq -r '.ticker')
        market=$(echo "$line" | jq -r '.market // ""')
        price=$(echo "$line" | jq -r '.price')
        size=$(echo "$line" | jq -r '.size')
        timestamp=$(echo "$line" | jq -r '.timestamp')
        
        # Extract team from ticker (last segment after hyphen)
        team=$(echo "$ticker" | rev | cut -d'-' -f1 | rev)
        
        # Parse market to get game (e.g., "Chicago at New York Winner?" -> "CHI@NYK")
        if echo "$market" | grep -q " at "; then
            team1=$(echo "$market" | sed 's/ at .*//' | awk '{print $1}' | cut -c1-3 | tr '[:lower:]' '[:upper:]')
            team2=$(echo "$market" | sed 's/.* at //' | sed 's/ Winner.*//' | awk '{print $1}' | cut -c1-3 | tr '[:lower:]' '[:upper:]')
            game="${team1}@${team2}"
        else
            game="$ticker"
        fi
        
        # Shorten timestamp
        ts_short=$(echo "$timestamp" | cut -d'.' -f1 | sed 's/T/ /')
        
        # Format price
        if [ $(echo "$price < 1" | bc -l) -eq 1 ]; then
            price_fmt=$(printf "$%.4f" "$price")
        else
            price_fmt=$(printf "$%.2f" "$price")
        fi
        
        OPEN_POSITIONS="${OPEN_POSITIONS}  ${team} ${game} | Entry: ${price_fmt} | Size: ${size}\n"
        OPEN_COUNT=$((OPEN_COUNT + 1))
    done < <(jq -c '.[] | select(.action == "BUY" and .pnl == 0)' "$FLIP_TRADES" | tail -10)
fi

# Format P&L signs
if (( $(echo "$TOTAL_PNL >= 0" | bc -l) )); then
    TOTAL_PNL_DISPLAY="+$${TOTAL_PNL_FMT}"
else
    TOTAL_PNL_DISPLAY="-$$(echo "${TOTAL_PNL_FMT#-}" | tr -d '-')"
fi

# Build report message
TIMESTAMP=$(date '+%Y-%m-%d %H:%M UTC')

REPORT="📊 **UNIFIED PAPER TRADING REPORT**
━━━━━━━━━━━━━━━━━━━━━━
**SUPERBOT** (Crypto 15-min)
💰 Balance: \$${SB_BALANCE_FMT} | Trades: ${SB_TRADES} | W: ${SB_WINS} L: ${SB_LOSSES} | WR: ${SB_WR_FMT}%
💵 P&L: \$${SB_PNL_FMT} | Open: ${SB_OPEN}

**FLIP BOT** (NBA Game Winners)
💰 Balance: \$${FLIP_BALANCE_FMT} | Trades: ${FLIP_TRADES} | Open: ${FLIP_POS_FMT}
💵 P&L: \$${FLIP_PNL_FMT}

**COMBINED TOTAL**
💰 Total Balance: \$${TOTAL_BALANCE_FMT} (started \$${TOTAL_START_FMT})
💵 Total P&L: $${TOTAL_PNL_DISPLAY}
━━━━━━━━━━━━━━━━━━━━━━"

# Add open positions if any
if [ -n "$OPEN_POSITIONS" ]; then
    REPORT="${REPORT}
**OPEN POSITIONS (last 10):**
$(printf '%b' "$OPEN_POSITIONS")"
fi

FULL_MESSAGE="${REPORT}
⏰ Posted: ${TIMESTAMP}"

# Post to Discord
PAYLOAD=$(printf '{"content": %s}' "$(echo "$FULL_MESSAGE" | jq -Rs .)")
curl -s -H "Content-Type: application/json" \
    -d "$PAYLOAD" \
    "$WEBHOOK_URL" > /dev/null

echo "Report posted at $(date)"
