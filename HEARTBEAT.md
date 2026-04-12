# HEARTBEAT.md

## Periodic Stats Report (Every 15 min)

Every ~15 minutes, check the superbot status and send Tony the stats via Discord.

### What to do:
1. Run this Python script to get fresh stats:
```python
import requests, json
from kalshi_py.auth import KalshiAuth

access_key = '2af9792d-cadd-4067-a861-b9bff4238248'
private_key_path = '/home/ubuntu/.openclaw/workspace/workers/superbot/kalshi_private_key.pem'
with open(private_key_path) as f:
    private_key_data = f.read()

auth = KalshiAuth(access_key_id=access_key, private_key_pem=private_key_data)
base_url = 'https://api.elections.kalshi.com/trade-api/v2'

# Get balance
headers = auth.get_auth_headers('GET', '/portfolio/balance')
resp = requests.get(f'{base_url}/portfolio/balance', headers=headers)
bal = resp.json()
cash = int(bal['balance']) / 100
portfolio = int(bal['portfolio_value']) / 100

# Get positions
headers2 = auth.get_auth_headers('GET', '/portfolio/positions')
resp2 = requests.get(f'{base_url}/portfolio/positions', headers=headers2)
positions = resp2.json()
open_pos = []
for p in positions.get('market_positions', []):
    if float(p['position_fp']) != 0:
        open_pos.append(f"{p['ticker'].split('-')[0][2:]}: {'YES' if float(p['position_fp']) > 0 else 'NO'} @ ${float(p['total_traded_dollars'])/abs(float(p['position_fp']))/100:.2f}")

# Read trades from log
import subprocess
result = subprocess.run(['grep', 'Trade recorded:', '/home/ubuntu/.openclaw/workspace/workers/superbot/superbot_live.log'], capture_output=True, text=True)
lines = result.stdout.strip().split('\n')

# Parse last N trades
trades = []
for line in lines[-50:]:
    parts = line.split('PnL=')
    if len(parts) == 2:
        ticker_part = line.split('Trade recorded: ')[1].split(' ')[0] if 'Trade recorded:' in line else ''
        side = 'YES' if 'yes' in line.lower() else 'NO'
        try:
            pnl = float(parts[1].split()[0])
        except:
            pnl = 0
        if ticker_part:
            coin = ticker_part.split('-')[1] if len(ticker_part.split('-')) > 1 else ticker_part
            trades.append({'coin': coin, 'side': side, 'pnl': pnl})

wins = [t for t in trades if t['pnl'] > 0]
losses = [t for t in trades if t['pnl'] < 0]
total_pnl = sum(t['pnl'] for t in trades)
avg_win = sum(t['pnl'] for t in wins) / len(wins) if wins else 0
avg_loss = sum(t['pnl'] for t in losses) / len(losses) if losses else 0
win_rate = len(wins) / len(trades) * 100 if trades else 0

print(f"STATS_UPDATE: {len(trades)} trades | {len(wins)}W/{len(losses)}L | WR {win_rate:.0f}% | PnL {total_pnl:+.2f} | Cash ${cash:.2f} | Portfolio ${portfolio:.2f}")
if open_pos:
    print(f"POSITIONS: {', '.join(open_pos)}")
```

2. If there are new settled trades or the stats have changed significantly, send the stats to Tony on Discord using the message tool with channel discord.

3. Format the message as:
```
📊 SESSION STATS (since restart)

W/L: {wins}W / {losses}L
Win rate: {win_rate:.0f}%
Total P&L: ${total_pnl:+.2f}
Avg win: ${avg_win:.2f}
Avg loss: ${avg_loss:.2f}
Profit factor: {abs(avg_win/avg_loss) if avg_loss else 0:.2f}x

Cash: ${cash:.2f}
Portfolio: ${portfolio:.2f}
Total: ${cash + portfolio:.2f}

Open: {open_positions}
```
