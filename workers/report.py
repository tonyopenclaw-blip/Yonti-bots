#!/usr/bin/env python3
"""
Unified Paper Trading Report
Combines Superbot + Flip Bot into one view
Last 10 open positions + last 10 closed trades, sorted by time (newest first)
"""

import json
import re
from pathlib import Path
from datetime import datetime

SUPERBOT_DIR = Path("/home/ubuntu/.openclaw/workspace/workers/superbot")
FLIP_DIR = Path("/home/ubuntu/.openclaw/workspace/workers/flip")
OUTPUT_FILE = Path("/home/ubuntu/.openclaw/workspace/workers/unified_report.html")


def load_json(path):
    """Load a JSON file, return empty dict/list if missing or invalid."""
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def load_superbot_trades():
    data = load_json(SUPERBOT_DIR / "report.json")
    return data.get("trades", [])


def load_flip_trades():
    data = load_json(FLIP_DIR / "data" / "flip_trades.json")
    if isinstance(data, list):
        return data
    return []


def parse_nba_game_from_market(market):
    """Parse NBA market title like 'Chicago at New York Winner?' -> 'CHI@NYK'"""
    if not market:
        return ""
    # Strip " Winner?" or similar suffixes
    cleaned = re.sub(r'\s*Winner\??\s*$', '', market, flags=re.IGNORECASE).strip()
    if ' at ' in cleaned:
        parts = cleaned.split(' at ')
        team1 = parts[0].strip()
        team2 = parts[1].strip()
        # Convert to 3-letter abbreviations (take first 3 chars)
        abbr1 = team1[:3].upper()
        abbr2 = team2[:3].upper()
        return f"{abbr1}@{abbr2}"
    return cleaned


def parse_side_from_ticker_nba(ticker, market=""):
    """Extract team name from NBA ticker (last part after hyphens)."""
    if not ticker:
        return ""
    # Ticker format: KXNBAGAME-26APR01ATLHOU-ATL
    # Last segment after last hyphen is the team
    parts = ticker.split('-')
    if len(parts) >= 2:
        return parts[-1].upper()
    return ""


def is_nba_market(ticker, market):
    """Detect if this is an NBA market based on ticker prefix."""
    return bool(re.match(r'^KXNBAGAME', ticker or ''))


def normalize_superbot_trade(t):
    """
    Convert a superbot trade dict to unified format.
    Fields: ticker, side, entry_price, exit_price, size, pnl,
            strategy, open_time, close_time, exit_reason
    """
    timestamp = t.get("close_time") or t.get("open_time") or ""
    return {
        "bot": "Superbot",
        "timestamp": timestamp,
        "ticker": t.get("ticker", ""),
        "side": t.get("side", "").upper(),
        "entry": t.get("entry_price", 0),
        "exit": t.get("exit_price", 0),
        "size": t.get("size", 0),
        "pnl": t.get("pnl", 0),
        "market": t.get("strategy", ""),
        "exit_reason": t.get("exit_reason", ""),
        "is_nba": False,
    }


def normalize_flip_trade(t):
    """
    Convert a flip trade dict to unified format.
    Fields: timestamp, ticker, market, action, side, price, size, pnl, game_key
    For NBA: BUY action = bought YES on that team.
    """
    timestamp = t.get("timestamp", "")
    action = t.get("action", "").upper()
    ticker = t.get("ticker", "")
    market = t.get("market", "")
    is_nba = is_nba_market(ticker, market)

    # Determine side display
    if is_nba:
        # For NBA, side is the team name
        side_display = parse_side_from_ticker_nba(ticker, market)
    else:
        # For crypto, BUY = YES, SELL = NO
        side_display = "YES" if action == "BUY" else "NO"

    # Determine entry/exit
    if action == "BUY":
        entry = t.get("price", 0)
        exit_price = 0
    else:  # SELL
        entry = 0
        exit_price = t.get("price", 0)

    # Coin/Game display
    if is_nba:
        coin_game = parse_nba_game_from_market(market)
    else:
        coin_game = t.get("ticker", "") or market

    return {
        "bot": "Flip",
        "timestamp": timestamp,
        "ticker": ticker,
        "side": side_display,
        "entry": entry,
        "exit": exit_price,
        "size": t.get("size", 0),
        "pnl": t.get("pnl", 0),
        "market": coin_game,  # Use parsed coin/game for display
        "exit_reason": "",
        "is_nba": is_nba,
    }


def is_closed_trade(t):
    """
    Determine if a trade is closed.
    - SELL action → closed
    - Has close_time or exit_reason → closed
    - Has non-zero pnl → closed
    """
    action = t.get("action", "").upper()
    if action == "SELL":
        return True
    if t.get("pnl", 0) != 0:
        return True
    if t.get("exit_reason", ""):
        return True
    if t.get("timestamp", "") and "close_time" in t and t.get("close_time"):
        return True
    return False


def timestamp_key(t):
    """Sort key: use timestamp string, fallback to empty string."""
    return t.get("timestamp", "")


def generate_report():
    # Load raw data
    superbot_trades_raw = load_superbot_trades()
    flip_trades_raw = load_flip_trades()
    flip_stats = load_json(FLIP_DIR / "data" / "flip_stats.json")
    superbot_stats = load_json(SUPERBOT_DIR / "report.json")

    # Normalize to unified format
    all_trades = []
    for t in superbot_trades_raw:
        all_trades.append(normalize_superbot_trade(t))
    for t in flip_trades_raw:
        all_trades.append(normalize_flip_trade(t))

    # Sort by timestamp descending (newest first)
    all_trades.sort(key=timestamp_key, reverse=True)

    # Separate open and closed
    open_positions = [t for t in all_trades if not is_closed_trade(t)]
    closed_trades = [t for t in all_trades if is_closed_trade(t)]

    # Take last 10 of each (already sorted newest-first, so last 10 = most recent)
    open_positions = open_positions[:10]
    closed_trades = closed_trades[:10]

    # Compute per-bot stats from closed trades
    superbot_closed = [t for t in closed_trades if t.get("bot") == "Superbot"]
    flip_closed = [t for t in closed_trades if t.get("bot") == "Flip"]

    superbot_pnl = sum(t.get("pnl", 0) for t in superbot_closed)
    flip_pnl = sum(t.get("pnl", 0) for t in flip_closed)
    total_pnl = superbot_pnl + flip_pnl

    wins = [t for t in closed_trades if t.get("pnl", 0) > 0]
    losses = [t for t in closed_trades if t.get("pnl", 0) < 0]
    win_rate = len(wins) / len(closed_trades) * 100 if closed_trades else 0

    # Balances
    superbot_balance = superbot_stats.get("ending_balance", 100.0)
    flip_balance = flip_stats.get("balance", 100.0)

    # Largest win/loss
    pnls = [t.get("pnl", 0) for t in closed_trades]
    largest_win = max(pnls, default=0)
    largest_loss = min(pnls, default=0)

    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    # Helper: format price
    def fmt_price(p):
        if p >= 1:
            return f"${p:.2f}"
        else:
            return f"${p:.4f}"

    def fmt_pnl(p):
        sign = "+" if p >= 0 else ""
        if abs(p) >= 1:
            return f"{sign}${p:.2f}"
        else:
            return f"{sign}${p:.4f}"

    def pnl_class(p):
        if p > 0:
            return "positive"
        elif p < 0:
            return "negative"
        return ""

    def short_time(ts):
        """Shorten timestamp to YYYY-MM-DD HH:MM:SS"""
        return ts[:19] if ts else ""

    # Build HTML
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Unified Paper Trading Report</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0d1117;
            color: #c9d1d9;
            padding: 20px;
            font-size: 14px;
        }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        h1 {{ color: #58a6ff; margin-bottom: 20px; font-size: 24px; }}
        h2 {{ color: #c9d1d9; margin: 25px 0 10px; font-size: 16px; border-bottom: 1px solid #30363d; padding-bottom: 5px; }}

        .summary {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 12px;
            margin-bottom: 25px;
        }}
        .stat-card {{
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 8px;
            padding: 12px 15px;
        }}
        .stat-card .label {{ color: #8b949e; font-size: 11px; text-transform: uppercase; }}
        .stat-card .value {{ font-size: 20px; font-weight: bold; margin-top: 4px; }}
        .positive {{ color: #3fb950; }}
        .negative {{ color: #f85149; }}
        .neutral {{ color: #58a6ff; }}

        table {{ width: 100%; border-collapse: collapse; background: #161b22; border-radius: 8px; overflow: hidden; margin-bottom: 30px; }}
        th, td {{ padding: 10px 12px; text-align: left; border-bottom: 1px solid #30363d; }}
        th {{ background: #21262d; color: #8b949e; font-size: 11px; text-transform: uppercase; font-weight: 600; }}
        tr:hover {{ background: #1c2128; }}
        tr:last-child td {{ border-bottom: none; }}

        .section-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
        }}
        .section-header h2 {{ margin: 0; border: none; }}
        .badge {{
            background: #238636; color: white; padding: 2px 8px; border-radius: 10px;
            font-size: 11px;
        }}
        .badge-closed {{ background: #da3633; }}
        .empty {{ color: #8b949e; font-style: italic; padding: 20px; text-align: center; background: #161b22; border-radius: 8px; }}

        .bot-tag {{
            display: inline-block;
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 10px;
            font-weight: bold;
            text-transform: uppercase;
        }}
        .bot-superbot {{ background: #1f6feb; color: white; }}
        .bot-flip {{ background: #a371f7; color: white; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 Unified Paper Trading Report</h1>
        <p style="color: #8b949e; margin-bottom: 20px;">Generated: {now_str}</p>

        <div class="summary">
            <div class="stat-card">
                <div class="label">Superbot Balance</div>
                <div class="value neutral">${superbot_balance:.2f}</div>
            </div>
            <div class="stat-card">
                <div class="label">Flip Balance</div>
                <div class="value neutral">${flip_balance:.2f}</div>
            </div>
            <div class="stat-card">
                <div class="label">Total P&L</div>
                <div class="value {'positive' if total_pnl >= 0 else 'negative'}">{'+' if total_pnl >= 0 else ''}${total_pnl:.2f}</div>
            </div>
            <div class="stat-card">
                <div class="label">Win Rate</div>
                <div class="value neutral">{win_rate:.1f}%</div>
            </div>
            <div class="stat-card">
                <div class="label">Wins / Losses</div>
                <div class="value neutral">{len(wins)} / {len(losses)}</div>
            </div>
            <div class="stat-card">
                <div class="label">Open Positions</div>
                <div class="value neutral">{len(open_positions)}</div>
            </div>
            <div class="stat-card">
                <div class="label">Closed Trades</div>
                <div class="value neutral">{len(closed_trades)}</div>
            </div>
            <div class="stat-card">
                <div class="label">Largest Win</div>
                <div class="value positive">${largest_win:.2f}</div>
            </div>
            <div class="stat-card">
                <div class="label">Largest Loss</div>
                <div class="value negative">${largest_loss:.2f}</div>
            </div>
        </div>

        <div class="section-header">
            <h2>📌 Open Positions (last 10 by time)</h2>
            <span class="badge">{len(open_positions)} open</span>
        </div>
"""

    if open_positions:
        html += """<table>
            <thead>
                <tr>
                    <th>Bot</th>
                    <th>Coin/Game</th>
                    <th>Side</th>
                    <th>Entry</th>
                    <th>Shares</th>
                    <th>Time</th>
                </tr>
            </thead>
            <tbody>
"""
        for t in open_positions:
            bot_tag = 'bot-superbot' if t.get('bot') == 'Superbot' else 'bot-flip'
            market = t.get('market', t.get('ticker', ''))
            side = t.get('side', '')
            entry = t.get('entry', 0)
            size = t.get('size', 0)
            ts = short_time(t.get('timestamp', ''))
            html += f"""                <tr>
                    <td><span class="bot-tag {bot_tag}">{t.get('bot', '?')}</span></td>
                    <td>{market}</td>
                    <td>{side}</td>
                    <td>{fmt_price(entry)}</td>
                    <td>{size:.2f}</td>
                    <td>{ts}</td>
                </tr>
"""
        html += """            </tbody>
        </table>
"""
    else:
        html += '<div class="empty">No open positions</div>\n'

    html += f"""
        <div class="section-header">
            <h2>📋 Closed Trades (last 10 by time)</h2>
            <span class="badge badge-closed">{len(closed_trades)} closed</span>
        </div>
"""

    if closed_trades:
        html += """<table>
            <thead>
                <tr>
                    <th>Bot</th>
                    <th>Coin/Game</th>
                    <th>Side</th>
                    <th>Shares</th>
                    <th>PnL</th>
                    <th>Time</th>
                </tr>
            </thead>
            <tbody>
"""
        for t in closed_trades:
            bot_tag = 'bot-superbot' if t.get('bot') == 'Superbot' else 'bot-flip'
            market = t.get('market', t.get('ticker', ''))
            side = t.get('side', '')
            size = t.get('size', 0)
            pnl = t.get('pnl', 0)
            ts = short_time(t.get('timestamp', ''))
            pnl_cls = pnl_class(pnl)
            html += f"""                <tr>
                    <td><span class="bot-tag {bot_tag}">{t.get('bot', '?')}</span></td>
                    <td>{market}</td>
                    <td>{side}</td>
                    <td>{size:.2f}</td>
                    <td class="{pnl_cls}">{fmt_pnl(pnl)}</td>
                    <td>{ts}</td>
                </tr>
"""
        html += """            </tbody>
        </table>
"""
    else:
        html += '<div class="empty">No closed trades</div>\n'

    html += """    </div>
</body>
</html>"""

    OUTPUT_FILE.write_text(html)
    print(f"Report saved to {OUTPUT_FILE}")
    print(f"Summary: {len(open_positions)} open, {len(closed_trades)} closed, P&L: ${total_pnl:.2f}")
    print(f"Superbot trades loaded: {len(superbot_trades_raw)}, Flip trades loaded: {len(flip_trades_raw)}")

    return {
        "open_positions": open_positions,
        "closed_trades": closed_trades,
        "superbot_balance": superbot_balance,
        "flip_balance": flip_balance,
        "total_pnl": total_pnl,
        "win_rate": win_rate,
        "wins": len(wins),
        "losses": len(losses),
        "largest_win": largest_win,
        "largest_loss": largest_loss,
    }


if __name__ == "__main__":
    generate_report()
