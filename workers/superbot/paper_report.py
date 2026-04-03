#!/usr/bin/env python3
"""
Paper Trading Report - Posts Superbot performance to Discord webhook.
"""

import json
import sys
import subprocess
from datetime import datetime

def load_report():
    """Load the latest superbot report."""
    with open('/home/ubuntu/.openclaw/workspace/workers/superbot/report.json', 'r') as f:
        return json.load(f)

def format_trade(t):
    """Format a single trade as emoji line."""
    emoji = "✅" if t['pnl'] > 0 else "❌"
    side_emoji = "📈" if t['side'] == 'yes' else "📉"
    return f"  {emoji} {side_emoji} {t['ticker'].split('-')[1][-6:]} | E=${t['entry_price']:.3f} → X=${t['exit_price']:.3f} | PnL ${t['pnl']:+.4f} | {t['strategy']}"

def build_report(d):
    """Build short Discord embed from report data."""
    pnl = d['total_pnl']
    pnl_emoji = "🟢" if pnl >= 0 else "🔴"
    
    open_count = d.get('open_positions', 0)
    open_str = f" | Open: {open_count}" if open_count > 0 else ""
    
    # Calculate avg_win and avg_loss from trades
    winning_trades = [t['pnl'] for t in d['trades'] if t['pnl'] > 0]
    losing_trades = [t['pnl'] for t in d['trades'] if t['pnl'] < 0]
    avg_win = sum(winning_trades) / len(winning_trades) if winning_trades else 0
    avg_loss = sum(losing_trades) / len(losing_trades) if losing_trades else 0
    
    # Show last 5 trades only (to stay under 2000 chars)
    recent_trades = d['trades'][-5:]
    
    msg = f"**📊 YONTI PAPER TRADING**\n"
    msg += f"━━━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"**${d['starting_balance']:.2f} → ${d['ending_balance']:.2f}** {pnl_emoji} ${pnl:+.2f}\n"
    msg += f"WR: {d['win_rate']}% ({d['winning_trades']}W/{d['losing_trades']}L){open_str}\n"
    msg += f"**Trades:** {d['total_trades']} | **Best:** +${d['largest_win']:.4f} | **Worst:** ${d['largest_loss']:.4f}\n"
    msg += f"**Avg Win:** +${avg_win:.4f} | **Avg Loss:** ${avg_loss:.4f}\n"
    msg += f"\n**Last 5:**\n"
    
    for t in recent_trades:
        emoji = "✅" if t['pnl'] > 0 else "❌"
        side = "📈" if t['side'] == 'yes' else "📉"
        msg += f"{emoji} {side} {t['ticker'].split('-')[1][-6:]} E=${t['entry_price']:.3f} X=${t['exit_price']:.3f} PnL ${t['pnl']:+.4f}\n"
    
    msg += f"\n🤖 drift_buy/sell + trailing stop"
    
    return msg

def post_discord(message):
    """Post message to Discord via webhook."""
    webhook = "https://discord.com/api/webhooks/1486066262122430684/mLKWVlGJRyADWEnpDgx3n4QcI1B-JhAnDLyBHKwsK-BSmeo5lal5MYrrY_QiuOBqiNLy"
    
    cmd = [
        'curl', '-s', '-X', 'POST',
        '-H', 'Content-Type: application/json',
        '-d', json.dumps({'content': message}),
        webhook
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Failed to post to Discord: {result.stderr}")
        return False
    return True

if __name__ == '__main__':
    d = load_report()
    msg = build_report(d)
    print(msg)
    
    if len(sys.argv) > 1 and sys.argv[1] == '--discord':
        post_discord(msg)