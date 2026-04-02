#!/bin/bash
# Superbot Paper Trading Report - Posts to Discord
# Uses Python for JSON parsing and time conversion

WEBHOOK_URL="https://discord.com/api/webhooks/1486066262122430684/mLKWVlGJRyADWEnpDgx3n4QcI1B-JhAnDLyBHKwsK-BSmeo5lal5MYrrY_QiuOBqiNLy"

SUPERBOT_STATS="/home/ubuntu/.openclaw/workspace/workers/superbot/report.json"
SUPERBOT_REPORT_PY="/home/ubuntu/.openclaw/workspace/workers/superbot/report.py"
FLIP_STATS="/home/ubuntu/.openclaw/workspace/workers/flip/data/flip_stats.json"
FLIP_TRADES="/home/ubuntu/.openclaw/workspace/workers/flip/data/flip_trades.json"
THERMO_DATA="/home/ubuntu/.openclaw/workspace/workers/thermostat/data/thermostat_trades.json"
MESSAGE_FILE="/tmp/superbot_discord_msg.txt"

# Run the Python report generator to refresh stats
python3 "$SUPERBOT_REPORT_PY" > /dev/null 2>&1

# Generate Discord message using Python
python3 << 'PYTHON_SCRIPT'
import json
from datetime import datetime, timezone, timedelta

SUPERBOT_STATS = "/home/ubuntu/.openclaw/workspace/workers/superbot/report.json"
FLIP_STATS = "/home/ubuntu/.openclaw/workspace/workers/flip/data/flip_stats.json"
FLIP_TRADES = "/home/ubuntu/.openclaw/workspace/workers/flip/data/flip_trades.json"
THERMO_DATA = "/home/ubuntu/.openclaw/workspace/workers/thermostat/data/thermostat_trades.json"
MESSAGE_FILE = "/tmp/superbot_discord_msg.txt"

# Load Superbot stats
try:
    with open(SUPERBOT_STATS, 'r') as f:
        sb_stats = json.load(f)
except:
    sb_stats = {
        'ending_balance': 100.0,
        'total_trades': 0,
        'winning_trades': 0,
        'losing_trades': 0,
        'win_rate': 0,
        'total_pnl': 0,
        'open_positions': 0,
        'thermostat': 50,
        'last_10_open_trades': [],
        'last_10_closed_trades': []
    }

# Load Flip Bot stats
try:
    with open(FLIP_STATS, 'r') as f:
        fb_stats = json.load(f)
except:
    fb_stats = {
        'balance': 100.0,
        'total_trades': 0,
        'total_positions': 0,
        'session_pnl': 0
    }

# Load Flip Bot trades
try:
    with open(FLIP_TRADES, 'r') as f:
        fb_trades = json.load(f)
except:
    fb_trades = []

# Load Thermostat stats
try:
    with open(THERMO_DATA, 'r') as f:
        thermo_data = json.load(f)
        thermo_stats = thermo_data.get('stats', {})
except:
    thermo_stats = {
        'starting_balance': 100.0,
        'current_balance': 100.0,
        'total_trades': 0,
        'winning_trades': 0,
        'losing_trades': 0,
        'pending_trades': 0,
        'total_pnl': 0.0,
        'win_rate': 0.0
    }

# === SUPERBOT STATS ===
sb_balance = sb_stats.get('ending_balance', 100.0)
sb_trades = sb_stats.get('total_trades', 0)
sb_wins = sb_stats.get('winning_trades', 0)
sb_losses = sb_stats.get('losing_trades', 0)
sb_wr = sb_stats.get('win_rate', 0)
sb_pnl = sb_stats.get('total_pnl', 0)
sb_open = sb_stats.get('open_positions', 0)
sb_thermo = sb_stats.get('thermostat', 50)
sb_open_trades = sb_stats.get('last_10_open_trades', [])
sb_closed_trades = sb_stats.get('last_10_closed_trades', [])

# Calculate streak for Superbot
streak = 0
if sb_closed_trades:
    first_pnl = sb_closed_trades[0].get('pnl', 0)
    if first_pnl > 0:
        streak = 1
        for i in range(1, min(10, len(sb_closed_trades))):
            if sb_closed_trades[i].get('pnl', 0) > 0:
                streak += 1
            else:
                break
    elif first_pnl < 0:
        streak = -1
        for i in range(1, min(10, len(sb_closed_trades))):
            if sb_closed_trades[i].get('pnl', 0) < 0:
                streak -= 1
            else:
                break

# === FLIP BOT STATS ===
fb_balance = fb_stats.get('balance', 100.0)
fb_total_trades = fb_stats.get('total_trades', 0)
fb_open_pos = fb_stats.get('total_positions', 0)
fb_session_pnl = fb_stats.get('session_pnl', 0)

# Calculate Flip Bot W/L/WR from trades (only SELL trades with pnl != 0 count as closed)
fb_wins = 0
fb_losses = 0
for t in fb_trades:
    if t.get('action') == 'SELL' and t.get('pnl') != 0:
        if t.get('pnl', 0) > 0:
            fb_wins += 1
        elif t.get('pnl', 0) < 0:
            fb_losses += 1
fb_total_closed = fb_wins + fb_losses
fb_wr = (fb_wins / fb_total_closed * 100) if fb_total_closed > 0 else 0

# === THERMOSTAT STATS ===
th_balance = thermo_stats.get('current_balance', 100.0)
th_pnl = thermo_stats.get('total_pnl', 0.0)
th_wins = thermo_stats.get('winning_trades', 0)
th_losses = thermo_stats.get('losing_trades', 0)
th_wr = thermo_stats.get('win_rate', 0.0)

# === TIME ===
utc_now = datetime.now(timezone.utc)
utc_time_str = utc_now.strftime('%H:%M UTC')

# === FORMATTING HELPERS ===
def format_pnl(pnl):
    if pnl >= 0:
        return f"+${pnl:.2f}"
    else:
        return f"-${abs(pnl):.2f}"

def utc_to_eastern(ts_str):
    """Convert UTC timestamp to Eastern time (EDT in summer, EST in winter)"""
    try:
        # Handle ISO format with T separator and microseconds
        ts_str = ts_str.replace(' UTC', '').strip()
        ts_str = ts_str.replace('T', ' ').split('.')[0]  # Remove T and microseconds
        dt = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
        dt = dt.replace(tzinfo=timezone.utc)
        # EDT is UTC-4, EST is UTC-5 (April = EDT)
        et = dt.astimezone(timezone(timedelta(hours=-4)))
        return et.strftime('%H:%M:%S')
    except Exception as e:
        return '??:??:??'

def short_ticker_superbot(ticker):
    """Shorten Superbot ticker to coin symbol"""
    ticker = ticker.replace('KXBTC15M', 'BTC')
    ticker = ticker.replace('KXETH15M', 'ETH')
    ticker = ticker.replace('KXSOL15M', 'SOL')
    ticker = ticker.replace('KXXRP15M', 'XRP')
    ticker = ticker.replace('KXDOGE15M', 'DOGE')
    ticker = ticker.replace('KXHYPE15M', 'HYPE')
    ticker = ticker.replace('KXBNB15M', 'BNB')
    return ticker.split('-')[0]

def short_strategy(strategy):
    """Get short strategy name"""
    if '.' in strategy:
        return strategy.split('.')[-1]
    return strategy

def parse_flip_trade(trade):
    """Parse a Flip Bot trade into display format"""
    ticker = trade.get('ticker', '???')
    market = trade.get('market', '')
    side = trade.get('side', '')
    price = trade.get('price', 0)
    size = int(trade.get('size', 0))
    pnl = trade.get('pnl', 0)
    timestamp = trade.get('timestamp', '')
    action = trade.get('action', '')

    # Extract team from ticker (last segment after -)
    # e.g., KXNBAGAME-26APR03CHINYK-CHI -> CHI
    parts = ticker.split('-')
    team = parts[-1] if parts else '???'  # Our position team abbreviation

    # Use team as game short form (e.g., CHI, NYK, BKN)
    game_short = team

    # Determine YES/NO based on side
    vote = 'YES' if side == 'team_a' else 'NO' if side == 'team_b' else '?'

    # Strategy is always "spread" for Flip Bot
    strategy = 'spread'

    # Time in EDT
    et_time = utc_to_eastern(timestamp) if timestamp else '??:??:??'

    return et_time, team, game_short, strategy, vote, price, size, pnl, action

# === BUILD OPEN POSITIONS ===
all_open_positions = []

# Superbot open positions
for trade in sb_open_trades:
    ticker = short_ticker_superbot(trade.get('ticker', '???'))
    side = trade.get('side', '?').upper()
    entry = trade.get('entry_price', 0)
    size = int(trade.get('size', 0))
    strategy = short_strategy(trade.get('strategy', '?'))
    open_time = trade.get('open_time', '')
    et_time = utc_to_eastern(open_time) if open_time else '??:??:??'
    all_open_positions.append({
        'time': et_time,
        'bot': 'SB',
        'game': ticker,
        'strategy': strategy,
        'side': side,
        'entry': entry,
        'size': size,
        'pnl': 0,
        'action': 'OPEN'
    })

# Flip Bot open positions (action=BUY, pnl=0)
fb_open = [t for t in fb_trades if t.get('action') == 'BUY' and t.get('pnl') == 0 and t.get('market')]
# Deduplicate by ticker (keep latest)
fb_open_dict = {}
for t in fb_open:
    tk = t.get('ticker', '')
    ts = t.get('timestamp', '')
    if tk not in fb_open_dict or ts > fb_open_dict[tk].get('timestamp', ''):
        fb_open_dict[tk] = t

for trade in fb_open_dict.values():
    et_time, team, game_short, strategy, vote, price, size, pnl, action = parse_flip_trade(trade)
    all_open_positions.append({
        'time': et_time,
        'bot': 'FB',
        'game': game_short,
        'strategy': strategy,
        'side': team,
        'entry': price,
        'size': size,
        'pnl': 0,
        'action': 'OPEN'
    })

# Sort by time descending (most recent first)
all_open_positions.sort(key=lambda x: x['time'], reverse=True)

# === BUILD CLOSED TRADES ===
all_closed_trades = []

# Superbot closed trades
for trade in sb_closed_trades:
    ticker = short_ticker_superbot(trade.get('ticker', '???'))
    side = trade.get('side', '?').upper()
    entry = trade.get('entry_price', 0)
    exit_price = trade.get('exit_price', 0)
    size = int(trade.get('size', 0))
    pnl = trade.get('pnl', 0)
    strategy = short_strategy(trade.get('strategy', '?'))
    close_time = trade.get('close_time', '')
    et_time = utc_to_eastern(close_time) if close_time else '??:??:??'
    all_closed_trades.append({
        'time': et_time,
        'bot': 'SB',
        'game': ticker,
        'strategy': strategy,
        'side': side,
        'entry': entry,
        'exit': exit_price,
        'size': size,
        'pnl': pnl
    })

# Flip Bot closed trades (action=CLOSE or SELL, pnl!=0)
fb_closed_raw = [t for t in fb_trades if (t.get('action') == 'CLOSE' or t.get('action') == 'SELL') and t.get('pnl') != 0]
# Deduplicate by ticker (keep latest)
fb_closed_dict = {}
for t in fb_closed_raw:
    tk = t.get('ticker', '')
    ts = t.get('timestamp', '')
    if tk not in fb_closed_dict or ts > fb_closed_dict[tk].get('timestamp', ''):
        fb_closed_dict[tk] = t

for trade in fb_closed_dict.values():
    et_time, team, game_short, strategy, vote, price, size, pnl, action = parse_flip_trade(trade)
    # For closed trades, use the PnL from the trade
    pnl = trade.get('pnl', 0)
    # Exit price is in the 'price' field for CLOSE entries (but it's 0 for finalized markets)
    # Entry price was the original BUY price, but we don't have it in CLOSE entry
    # Show 0 for both since market is finalized
    all_closed_trades.append({
        'time': et_time,
        'bot': 'FB',
        'game': game_short,
        'strategy': strategy,
        'side': team,
        'entry': 0,  # Entry price not available in CLOSE entry
        'exit': trade.get('price', 0),  # This is 0 for finalized markets
        'size': size,
        'pnl': pnl
    })

# Sort by time descending (most recent first)
all_closed_trades.sort(key=lambda x: x['time'], reverse=True)

# Keep only last 25 closed trades
all_closed_trades = all_closed_trades[:25]

# === BUILD MESSAGE ===
lines = []
lines.append(f"📊 **PAPER TRADING** | {utc_time_str}")
lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
lines.append(f"**SUPERBOT** 💰 ${sb_balance:.2f} | P&L: {format_pnl(sb_pnl)} | W:{sb_wins} L:{sb_losses} | WR:{sb_wr:.0f}% | Streak:{streak} | 🌡️ {sb_thermo}")
lines.append(f"**THERMOSTAT** 💰 ${th_balance:.2f} | P&L: {format_pnl(th_pnl)} | W:{th_wins} L:{th_losses} | WR:{th_wr:.0f}%")
lines.append(f"**FLIP BOT** 💰 ${fb_balance:.2f} | P&L: {format_pnl(fb_session_pnl)} | W:{fb_wins} L:{fb_losses} | WR:{fb_wr:.0f}% | T:{fb_total_trades} | O:{fb_open_pos}")
lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

# Open positions
if all_open_positions:
    lines.append("**OPEN**")
    for pos in all_open_positions:
        line = f"`{pos['time']} {pos['bot']} {pos['game']} {pos['side']} E:${pos['entry']:.2f} S:{pos['size']} ⟳`"
        lines.append(line)

# Closed trades
if all_closed_trades:
    lines.append("**LAST 25**")
    for trade in all_closed_trades:
        if trade['bot'] == 'SB':
            line = f"`{trade['time']} {trade['bot']} {trade['game']} {trade['side']} E:${trade['entry']:.2f} X:${trade['exit']:.2f} S:{trade['size']} PnL:{format_pnl(trade['pnl'])}`"
        else:
            line = f"`{trade['time']} {trade['bot']} {trade['game']} {trade['side']} E:${trade['entry']:.2f} S:{trade['size']} PnL:{format_pnl(trade['pnl'])}`"
        lines.append(line)

message = '\n'.join(lines)
with open(MESSAGE_FILE, 'w') as f:
    f.write(message)

print("Message generated successfully")
PYTHON_SCRIPT

# Post to Discord
if [ -f "$MESSAGE_FILE" ]; then
    PAYLOAD=$(jq -Rs . < "$MESSAGE_FILE")
    curl -s -H "Content-Type: application/json" \
        -d "{\"content\": $PAYLOAD}" \
        "$WEBHOOK_URL" > /dev/null
    rm -f "$MESSAGE_FILE"
    echo "Superbot report posted at $(date)"
else
    echo "Failed to generate message"
fi
