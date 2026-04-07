# report.py - SuperPolybot Report Generator
# Generates JSON report for paper trading dashboard

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Trade:
    """Represents a closed trade."""
    ticker: str
    side: str
    entry_price: float
    exit_price: float
    contracts: float
    size: float
    pnl: float
    strategy: str
    open_time: str
    close_time: str
    exit_reason: str


class ReportGenerator:
    """Generates JSON reports for the paper trading dashboard."""

    def __init__(self, output_file: Path):
        self.output_file = output_file
        self.trades: List[Trade] = []
        self.open_trades: List[Dict] = []
        self.session_start: Optional[str] = None
        self.ending_balance: float = 100.0
        self.total_pnl: float = 0.0
        self.starting_balance: float = 100.0

    def start_session(self):
        """Mark session as started."""
        self.session_start = datetime.utcnow().isoformat() + "Z"
        logger.info(f"Report session started at {self.session_start}")

    def record_trade(self, trade: Trade):
        """Record a closed trade."""
        self.trades.append(trade)
        self._save()

    def record_open_trade(self, trade: Dict):
        """Record an open position."""
        self.open_trades.append(trade)
        self._save()

    def update_open_trades(self, open_trades: List[Dict]):
        """Update the list of open trades."""
        self.open_trades = open_trades
        self._save()

    def end_session(self, balance: float):
        """Mark session as ended and save final report."""
        self.ending_balance = balance
        self._save()

    def update_session_stats(
        self,
        balance: float,
        total_positions: int,
        positions_details: List[Dict] = None
    ):
        """Update session statistics."""
        self.ending_balance = balance

        # Recalculate P&L from closed trades
        closed_pnl = sum(t.pnl for t in self.trades)
        self.total_pnl = closed_pnl

        self._save()

    def _save(self):
        """Save report to JSON file."""
        # Calculate stats
        closed_trades = [t for t in self.trades if t.pnl != 0 or t.exit_price > 0]
        winning_trades = [t for t in closed_trades if t.pnl > 0]
        losing_trades = [t for t in closed_trades if t.pnl < 0]

        total_trades = len(closed_trades)
        win_rate = (
            len(winning_trades) / total_trades * 100
            if total_trades > 0 else 0
        )

        report = {
            "bot": "superpolybot",
            "bot_name": "SuperPolybot",
            "start_time": self.session_start or "",
            "end_time": datetime.utcnow().isoformat() + "Z",
            "starting_balance": self.starting_balance,
            "ending_balance": round(self.ending_balance, 2),
            "total_pnl": round(self.total_pnl, 2),
            "winning_trades": len(winning_trades),
            "losing_trades": len(losing_trades),
            "total_trades": total_trades,
            "win_rate": round(win_rate, 1),
            "trades": [
                {
                    "ticker": t.ticker,
                    "side": t.side,
                    "entry_price": round(t.entry_price, 4),
                    "exit_price": round(t.exit_price, 4),
                    "contracts": round(t.contracts, 2),
                    "shares": round(t.contracts, 2),
                    "pnl": round(t.pnl, 4),
                    "strategy": t.strategy,
                    "open_time": t.open_time,
                    "close_time": t.close_time,
                    "exit_reason": t.exit_reason,
                }
                for t in self.trades
            ],
            "last_10_open_trades": [
                {
                    "ticker": ot.get("condition_id", "")[:20],
                    "side": ot.get("side", ""),
                    "entry_price": round(ot.get("entry_price", 0), 4),
                    "current_price": round(ot.get("current_price", ot.get("entry_price", 0)), 4),
                    "contracts": round(ot.get("contracts", 0), 2),
                    "shares": round(ot.get("contracts", 0), 2),
                    "open_time": ot.get("open_time", ""),
                    "strategy": ot.get("strategy", "momentum"),
                }
                for ot in self.open_trades[-10:]
            ],
        }

        try:
            with open(self.output_file, 'w') as f:
                json.dump(report, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save report: {e}")

    def get_stats(self) -> Dict:
        """Get current stats as dict."""
        closed_trades = [t for t in self.trades if t.pnl != 0 or t.exit_price > 0]
        winning_trades = [t for t in closed_trades if t.pnl > 0]
        losing_trades = [t for t in closed_trades if t.pnl < 0]

        return {
            "balance": self.ending_balance,
            "pnl": self.total_pnl,
            "wins": len(winning_trades),
            "losses": len(losing_trades),
            "total": len(closed_trades),
            "win_rate": (
                len(winning_trades) / len(closed_trades) * 100
                if closed_trades else 0
            ),
        }
