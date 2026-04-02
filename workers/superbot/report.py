# report.py - Superbot Paper Trading Report Generator

import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any
from dataclasses import dataclass, field

from config import REPORT_FILE, REPORT_TITLE, PAPER_BALANCE

logger = logging.getLogger(__name__)


@dataclass
class Trade:
    """Record of a completed trade."""
    ticker: str
    side: str
    entry_price: float
    exit_price: float
    size: float
    pnl: float
    strategy: str
    open_time: str
    close_time: str
    exit_reason: str


@dataclass
class OpenPosition:
    """Record of an currently open position."""
    ticker: str
    side: str
    entry_price: float
    size: float
    strategy: str
    open_time: str
    current_price: float = 0.0  # Updated periodically


@dataclass
class SessionStats:
    """Trading session statistics."""
    start_time: str = ""
    end_time: str = ""
    starting_balance: float = PAPER_BALANCE
    ending_balance: float = PAPER_BALANCE
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    trades: List[Trade] = field(default_factory=list)  # Closed trades
    open_positions: int = 0  # Number of currently open positions
    open_trades: List[OpenPosition] = field(default_factory=list)  # Open trade details
    last_10_closed: List[dict] = field(default_factory=list)  # Last 10 closed trades for JSON


class ReportGenerator:
    """Generates HTML reports for paper trading sessions."""
    
    def __init__(self, output_file: Path = REPORT_FILE):
        self.output_file = output_file
        self.stats = SessionStats()
    
    def start_session(self):
        """Mark the start of a trading session."""
        self.stats.start_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        logger.info(f"Report session started: {self.stats.start_time}")
    
    def end_session(self, ending_balance: float):
        """Mark the end of a trading session."""
        self.stats.end_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        self.stats.ending_balance = ending_balance
        self.stats.total_pnl = ending_balance - self.stats.starting_balance
        logger.info(f"Report session ended: {self.stats.end_time}")
        self._generate_report()
    
    def record_trade(self, trade: Trade, open_position: OpenPosition = None):
        """Record a completed trade. Optionally pass the OpenPosition to remove from open_trades."""
        self.stats.trades.append(trade)
        self.stats.total_trades += 1
        
        # Track last 10 closed trades
        trade_dict = {
            "ticker": trade.ticker,
            "side": trade.side,
            "entry_price": trade.entry_price,
            "exit_price": trade.exit_price,
            "size": trade.size,
            "pnl": trade.pnl,
            "strategy": trade.strategy,
            "open_time": trade.open_time,
            "close_time": trade.close_time,
            "exit_reason": trade.exit_reason
        }
        self.stats.last_10_closed.insert(0, trade_dict)
        self.stats.last_10_closed = self.stats.last_10_closed[:10]
        
        # Remove from open trades if provided
        if open_position:
            self.stats.open_trades = [
                p for p in self.stats.open_trades
                if not (p.ticker == open_position.ticker and p.strategy == open_position.strategy)
            ]
        
        if trade.pnl > 0:
            self.stats.winning_trades += 1
            self.stats.largest_win = max(self.stats.largest_win, trade.pnl)
        elif trade.pnl < 0:
            self.stats.losing_trades += 1
            self.stats.largest_loss = min(self.stats.largest_loss, trade.pnl)
        
        logger.info(f"Trade recorded: {trade.ticker} {trade.side} {trade.strategy} PnL=${trade.pnl:.2f}")
    
    def update_open_positions(self, count: int, cash: float, current_pnl: float = None):
        """Update open position count and current cash mid-session."""
        self.stats.open_positions = count
        self.stats.ending_balance = cash
        if current_pnl is not None:
            self.stats.total_pnl = current_pnl
        # Save JSON mid-session for Discord webhook
        self._save_json_summary()
    
    def update_open_positions_details(self, positions: List[dict], cash: float):
        """
        Update open positions with full details for Discord webhook.
        
        positions: List of dicts with keys: ticker, side, entry_price, size, strategy, open_time, current_price
        """
        self.stats.open_positions = len(positions)
        self.stats.ending_balance = cash
        self.stats.total_pnl = cash - self.stats.starting_balance
        
        # Update open_trades list
        self.stats.open_trades = [
            OpenPosition(
                ticker=p.get('ticker', ''),
                side=p.get('side', ''),
                entry_price=p.get('entry_price', 0.0),
                size=p.get('size', 0.0),
                strategy=p.get('strategy', ''),
                open_time=p.get('open_time', ''),
                current_price=p.get('current_price', 0.0)
            )
            for p in positions
        ]
        
        self._save_json_summary()
    
    def update_session_stats(self, cash: float, positions_count: int, positions: List[dict] = None):
        """Update session stats mid-run for Discord reporting."""
        self.stats.ending_balance = cash
        self.stats.open_positions = positions_count
        self.stats.total_pnl = cash - self.stats.starting_balance
        
        # If positions details provided, update them too
        if positions is not None:
            self.stats.open_trades = [
                OpenPosition(
                    ticker=p.get('ticker', ''),
                    side=p.get('side', ''),
                    entry_price=p.get('entry_price', 0.0),
                    size=p.get('size', 0.0),
                    strategy=p.get('strategy', ''),
                    open_time=p.get('open_time', ''),
                    current_price=p.get('current_price', 0.0)
                )
                for p in positions
            ]
        
        self._save_json_summary()
    
    def _generate_report(self):
        """Generate the HTML report."""
        win_rate = (self.stats.winning_trades / self.stats.total_trades * 100) if self.stats.total_trades > 0 else 0
        
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{REPORT_TITLE}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0d1117;
            color: #c9d1d9;
            padding: 20px;
        }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        h1 {{ 
            color: #58a6ff;
            margin-bottom: 20px;
            font-size: 24px;
        }}
        .summary {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 30px;
        }}
        .stat-card {{
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 8px;
            padding: 15px;
        }}
        .stat-card .label {{
            color: #8b949e;
            font-size: 12px;
            text-transform: uppercase;
        }}
        .stat-card .value {{
            font-size: 24px;
            font-weight: bold;
            margin-top: 5px;
        }}
        .positive {{ color: #3fb950; }}
        .negative {{ color: #f85149; }}
        .neutral {{ color: #58a6ff; }}
        .trades-table {{
            width: 100%;
            border-collapse: collapse;
            background: #161b22;
            border-radius: 8px;
            overflow: hidden;
        }}
        .trades-table th, .trades-table td {{
            padding: 12px 15px;
            text-align: left;
            border-bottom: 1px solid #30363d;
        }}
        .trades-table th {{
            background: #21262d;
            color: #8b949e;
            font-size: 12px;
            text-transform: uppercase;
        }}
        .trades-table tr:hover {{
            background: #1c2128;
        }}
        .session-info {{
            color: #8b949e;
            font-size: 14px;
            margin-bottom: 20px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>{REPORT_TITLE} 📊</h1>
        <div class="session-info">
            Session: {self.stats.start_time} to {self.stats.end_time}
        </div>
        
        <div class="summary">
            <div class="stat-card">
                <div class="label">Starting Balance</div>
                <div class="value neutral">${self.stats.starting_balance:.2f}</div>
            </div>
            <div class="stat-card">
                <div class="label">Ending Balance</div>
                <div class="value {'positive' if self.stats.ending_balance >= self.stats.starting_balance else 'negative'}">${self.stats.ending_balance:.2f}</div>
            </div>
            <div class="stat-card">
                <div class="label">Total P&L</div>
                <div class="value {'positive' if self.stats.total_pnl >= 0 else 'negative'}">{'+' if self.stats.total_pnl >= 0 else ''}${self.stats.total_pnl:.2f}</div>
            </div>
            <div class="stat-card">
                <div class="label">Total Trades</div>
                <div class="value neutral">{self.stats.total_trades}</div>
            </div>
            <div class="stat-card">
                <div class="label">Win Rate</div>
                <div class="value neutral">{win_rate:.1f}%</div>
            </div>
            <div class="stat-card">
                <div class="label">Wins / Losses</div>
                <div class="value neutral">{self.stats.winning_trades} / {self.stats.losing_trades}</div>
            </div>
            <div class="stat-card">
                <div class="label">Largest Win</div>
                <div class="value positive">${self.stats.largest_win:.2f}</div>
            </div>
            <div class="stat-card">
                <div class="label">Largest Loss</div>
                <div class="value negative">${self.stats.largest_loss:.2f}</div>
            </div>
        </div>
        
        <h2 style="color: #c9d1d9; margin-bottom: 15px;">Trade History</h2>
        {self._generate_trades_table()}
    </div>
</body>
</html>"""
        
        self.output_file.write_text(html)
        logger.info(f"Report saved to {self.output_file}")
        
        # Also save a JSON summary for external scripts (e.g., Discord webhook)
        self._save_json_summary()
    
    def _save_json_summary(self):
        """Save a JSON summary of session stats for external consumption."""
        import json
        json_file = self.output_file.with_suffix('.json')
        
        total_closed = self.stats.total_trades
        win_rate = (self.stats.winning_trades / total_closed * 100) if total_closed > 0 else 0
        
        # Thermostat: 0-100 scale of how active the bot is (open positions vs MAX_OPEN_POSITIONS = 8)
        MAX_POSITIONS = 8  # MAX_OPEN_POSITIONS from config
        thermostat = min(100, int(self.stats.open_positions / MAX_POSITIONS * 100))
        
        # Last 10 open trades (currently open positions)
        last_10_open = [
            {
                "ticker": p.ticker,
                "side": p.side,
                "entry_price": p.entry_price,
                "size": p.size,
                "strategy": p.strategy,
                "open_time": p.open_time,
                "current_price": p.current_price
            }
            for p in self.stats.open_trades[-10:]
        ]
        
        # Last 10 closed trades
        last_10_closed = self.stats.last_10_closed[-10:]
        
        summary = {
            "start_time": self.stats.start_time,
            "end_time": self.stats.end_time,
            "starting_balance": self.stats.starting_balance,
            "ending_balance": self.stats.ending_balance,
            "total_pnl": self.stats.total_pnl,
            "total_trades": total_closed,
            "winning_trades": self.stats.winning_trades,
            "losing_trades": self.stats.losing_trades,
            "win_rate": round(win_rate, 1),
            "largest_win": self.stats.largest_win,
            "largest_loss": self.stats.largest_loss,
            "open_positions": self.stats.open_positions,
            "thermostat": thermostat,  # 0-100 scale
            "trades": [
                {
                    "ticker": t.ticker,
                    "side": t.side,
                    "entry_price": t.entry_price,
                    "exit_price": t.exit_price,
                    "size": t.size,
                    "pnl": t.pnl,
                    "strategy": t.strategy,
                    "open_time": t.open_time,
                    "close_time": t.close_time,
                    "exit_reason": t.exit_reason
                }
                for t in self.stats.trades
            ],
            "last_10_open_trades": last_10_open,
            "last_10_closed_trades": last_10_closed
        }
        
        json_file.write_text(json.dumps(summary, indent=2))
        logger.info(f"JSON summary saved to {json_file}")
    
    def _generate_trades_table(self) -> str:
        """Generate the trades table HTML."""
        if not self.stats.trades:
            return "<p>No trades in this session.</p>"
        
        rows = []
        for t in self.stats.trades:
            pnl_class = "positive" if t.pnl >= 0 else "negative"
            pnl_str = f"{'+' if t.pnl >= 0 else ''}{t.pnl:.2f}"
            
            strategy_badge = {
                "deep_buy": "🔵 DEEP",
                "drift_buy": "🟢 DRIFT BUY", 
                "drift_short": "🔴 DRIFT SHORT"
            }.get(t.strategy, t.strategy)
            
            rows.append(f"""
            <tr>
                <td>{t.ticker}</td>
                <td>{t.side.upper()}</td>
                <td>{strategy_badge}</td>
                <td>${t.entry_price:.4f}</td>
                <td>${t.exit_price:.4f}</td>
                <td>${t.size:.2f}</td>
                <td class="{pnl_class}">${pnl_str}</td>
                <td>{t.open_time}</td>
                <td>{t.close_time}</td>
                <td>{t.exit_reason}</td>
            </tr>
            """)
        
        return f"""
        <table class="trades-table">
            <thead>
                <tr>
                    <th>Ticker</th>
                    <th>Side</th>
                    <th>Strategy</th>
                    <th>Entry</th>
                    <th>Exit</th>
                    <th>Size</th>
                    <th>P&L</th>
                    <th>Opened</th>
                    <th>Closed</th>
                    <th>Exit Reason</th>
                </tr>
            </thead>
            <tbody>
                {''.join(rows)}
            </tbody>
        </table>
        """
