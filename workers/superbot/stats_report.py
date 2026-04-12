#!/usr/bin/env python3
"""Send superbot stats to Discord every 15 min via cron."""
import requests
import subprocess
import re
import json
from pathlib import Path
from kalshi_py.auth import KalshiAuth

DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1492688796938932267/O1rP8V0V0QntVzLV9HE8hT8Bew-4GofQStjz7Kd2FLZ_h0N5ntaKR_ehGzIeNQzeBDFC"

ACCESS_KEY = '2af9792d-cadd-4067-a861-b9bff4238248'
PRIVATE_KEY_PATH = '/home/ubuntu/.openclaw/workspace/workers/superbot/kalshi_private_key.pem'
LOG_FILE = '/home/ubuntu/.openclaw/workspace/workers/superbot/superbot_live.log'

def get_signal_stats():
    """Get signal outcome stats from signal_log.json."""
    signal_file = Path(__file__).parent / "signal_log.json"
    if not signal_file.exists():
        return None

    with open(signal_file) as f:
        signals = json.load(f)

    taken = [s for s in signals if s.get('action') == 'TAKEN']
    blocked = [s for s in signals if s.get('action') == 'BLOCKED']

    taken_settled = [s for s in taken if s.get('won') is not None]
    taken_won = [s for s in taken_settled if s.get('won') == True]
    taken_lost = [s for s in taken_settled if s.get('won') == False]

    blocked_settled = [s for s in blocked if s.get('won') is not None]
    blocked_won = [s for s in blocked_settled if s.get('won') == True]
    blocked_lost = [s for s in blocked_settled if s.get('won') == False]

    return {
        'taken': len(taken),
        'taken_settled': len(taken_settled),
        'taken_won': len(taken_won),
        'taken_lost': len(taken_lost),
        'taken_pending': len(taken) - len(taken_settled),
        'blocked': len(blocked),
        'blocked_settled': len(blocked_settled),
        'blocked_won': len(blocked_won),
        'blocked_lost': len(blocked_lost),
        'blocked_pending': len(blocked) - len(blocked_settled),
    }


def get_stats():
    with open(PRIVATE_KEY_PATH) as f:
        private_key_data = f.read()
    auth = KalshiAuth(access_key_id=ACCESS_KEY, private_key_pem=private_key_data)
    base_url = 'https://api.elections.kalshi.com/trade-api/v2'

    # Balance
    headers = auth.get_auth_headers('GET', '/portfolio/balance')
    resp = requests.get(f'{base_url}/portfolio/balance', headers=headers)
    bal = resp.json()
    cash = int(bal['balance']) / 100
    portfolio = int(bal['portfolio_value']) / 100

    # Positions
    headers2 = auth.get_auth_headers('GET', '/portfolio/positions')
    resp2 = requests.get(f'{base_url}/portfolio/positions', headers=headers2)
    positions = resp2.json()
    open_pos = []
    for p in positions.get('market_positions', []):
        if float(p['position_fp']) != 0:
            ticker = p['ticker']
            series = ticker.split('-')[0]
            coin = series[2:5] if len(series) > 5 else series
            side = '+' if float(p['position_fp']) > 0 else '-'
            contracts = abs(float(p['position_fp']))
            cost = float(p['total_traded_dollars'])
            avg = cost / contracts / 100 if contracts else 0
            open_pos.append(f"{coin} {side}{contracts}@{avg:.2f}")

    # Trades from log (last 30)
    with open(LOG_FILE) as f:
        content = f.read()
    pattern = r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*Trade recorded: ([^\s]+) (\w+) .*PnL=\$(-?[\d.]+)'
    matches = re.findall(pattern, content)

    ticker_to_coin = {}
    for m in matches:
        ticker = m[1]
        parts = ticker.split('-')
        if len(parts) >= 1:
            series = parts[0]
            if len(series) >= 6:
                ticker_to_coin[ticker] = series[2:5]

    trades = []
    for m in matches:
        time_str, ticker, side, pnl = m
        time_only = time_str[11:16]
        coin = ticker_to_coin.get(ticker, '???')
        try:
            pnl_val = float(pnl)
            if time_only >= '22:00':  # session start
                trades.append({'time': time_only, 'coin': coin, 'pnl': pnl_val})
        except:
            pass

    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] < 0]
    total_pnl = sum(t['pnl'] for t in trades)
    avg_win = sum(t['pnl'] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t['pnl'] for t in losses) / len(losses) if losses else 0
    win_rate = len(wins) / len(trades) * 100 if trades else 0
    pf = abs(avg_win / avg_loss) if avg_loss else 0

    return {
        'trades': trades[-10:],  # last 10
        'total': len(trades),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': win_rate,
        'total_pnl': total_pnl,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'pf': pf,
        'cash': cash,
        'portfolio': portfolio,
        'open_pos': open_pos,
        'signals': get_signal_stats(),
    }

def format_message(s):
    lines = [
        f"📊 SUPERBOT SESSION STATS",
        f"━━━━━━━━━━━━━━━━━━━━━━",
        f"Trades: {s['total']} | {s['wins']}W / {s['losses']}L | WR **{s['win_rate']:.0f}%**",
        f"Total P&L: **${s['total_pnl']:+.2f}** | Avg win: ${s['avg_win']:.2f} | Avg loss: ${s['avg_loss']:.2f}",
        f"Profit factor: {s['pf']:.2f}x",
        f"Cash: ${s['cash']:.2f} | Portfolio: ${s['portfolio']:.2f} | **Total: ${s['cash']+s['portfolio']:.2f}**",
    ]
    if s['open_pos']:
        lines.append(f"Open: {', '.join(s['open_pos'])}")
    if s['trades']:
        last = s['trades'][-5:]
        lines.append("Recent:")
        for t in last:
            e = "✅" if t['pnl'] > 0 else "❌"
            lines.append(f"  {e} {t['time']} | {t['coin']} | ${t['pnl']:+.2f}")

    # Signal outcomes
    sig = s.get('signals')
    if sig:
        lines.append("")
        lines.append(f"📡 SIGNAL OUTCOMES")
        lines.append(f"  TAKEN: {sig['taken']} | {sig['taken_settled']} settled | {sig['taken_pending']} pending")
        if sig['taken_settled'] > 0:
            wr = sig['taken_won'] / sig['taken_settled'] * 100
            lines.append(f"    Win rate: {sig['taken_won']}W / {sig['taken_lost']}L = **{wr:.0f}%**")
        if sig['blocked'] > 0:
            lines.append(f"  BLOCKED: {sig['blocked']} | {sig['blocked_settled']} settled | {sig['blocked_pending']} pending")
            if sig['blocked_settled'] > 0:
                wr = sig['blocked_won'] / sig['blocked_settled'] * 100
                lines.append(f"    Would have won: {sig['blocked_won']} | Would have lost: {sig['blocked_lost']} (**{wr:.0f}%** WR)")

    return '\n'.join(lines)

if __name__ == '__main__':
    s = get_stats()
    msg = format_message(s)
    print(msg)
    # Send to Discord webhook
    try:
        requests.post(DISCORD_WEBHOOK, json={"content": msg}, timeout=10)
    except Exception as e:
        print(f"Discord webhook error: {e}")
