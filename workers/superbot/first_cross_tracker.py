#!/usr/bin/env python3
"""
🎯 First Cross Tracker - Non-invasive market prediction analyzer
Tracks whether the first cross through $0.50 predicts final direction.
Runs alongside Superbot/Recorder without affecting trading behavior.
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Set
from dataclasses import dataclass, asdict

# Add parent dir to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from config import (
    KALSHI_ACCESS_KEY, COINS, SERIES_TICKERS,
    LOG_DIR, LOG_LEVEL, LOG_FORMAT, LOG_DATE_FORMAT
)
from kalshi_api import KalshiAPI

# =============================================================================
# LOGGING SETUP
# =============================================================================
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "first_cross_tracker.log"

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format=LOG_FORMAT,
    datefmt=LOG_DATE_FORMAT,
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# =============================================================================
# CONFIG
# =============================================================================
OUTPUT_FILE = Path(__file__).parent / "first_cross_data.json"
POLL_INTERVAL_SEC = 2  # Poll every 2 seconds for active markets

# Midpoint for cross detection
MIDPOINT = 0.50


@dataclass
class MarketTracking:
    """Tracks first cross data for a single market."""
    coin: str
    ticker: str
    market_time: str  # Series ticker like "KXBT15M-26APR030600-00"
    first_cross_direction: Optional[str] = None  # "up" or "down"
    first_cross_price: Optional[float] = None
    first_cross_ts: Optional[str] = None
    samples_above_50: Set[int] = None  # Track which seconds were above 50
    samples_below_50: Set[int] = None  # Track which seconds were below 50
    started_tracking: bool = False
    finalized: bool = False
    final_price: Optional[float] = None
    final_direction: Optional[str] = None
    correct: Optional[bool] = None
    
    def __post_init__(self):
        if self.samples_above_50 is None:
            self.samples_above_50 = set()
        if self.samples_below_50 is None:
            self.samples_below_50 = set()


class FirstCrossTracker:
    """
    Tracks first crosses through $0.50 midpoint for all coin markets.
    
    Non-invasive: Only reads data, never trades.
    Runs alongside Superbot/Recorder to collect prediction accuracy stats.
    """
    
    def __init__(self):
        self.api = KalshiAPI(access_key=KALSHI_ACCESS_KEY)
        self.tracked_markets: Dict[str, MarketTracking] = {}
        self.output_file = OUTPUT_FILE
        self.poll_count = 0
        
        # Load existing data to avoid duplicates
        self.existing_tickers: Set[str] = set()
        self._load_existing_data()
        
        logger.info("=" * 60)
        logger.info("🎯 FIRST CROSS TRACKER INITIALIZED!")
        logger.info(f"Coins: {', '.join(COINS)}")
        logger.info(f"Output file: {self.output_file}")
        logger.info(f"Existing records: {len(self.existing_tickers)} markets")
        logger.info("=" * 60)
    
    def _load_existing_data(self):
        """Load existing tickers to avoid duplicate entries."""
        if self.output_file.exists():
            try:
                with open(self.output_file, 'r') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self.existing_tickers = {r.get('ticker', '') for r in data if r.get('ticker')}
                logger.info(f"Loaded {len(self.existing_tickers)} existing market records")
            except json.JSONDecodeError:
                logger.warning("Could not parse existing first_cross_data.json")
    
    def _extract_coin(self, ticker: str) -> str:
        """Extract coin symbol from ticker like KXBTC15M-26APR030600-00"""
        parts = ticker.split("-")
        if parts:
            series = parts[0]
            if series.startswith("KX") and len(series) >= 5:
                return series[2:5]  # BTC from KXBTC15M
        return "UNK"
    
    def _extract_market_time(self, ticker: str) -> str:
        """Extract market time from ticker like KXBTC15M-26APR030600-00"""
        parts = ticker.split("-")
        if len(parts) >= 3:
            return f"{parts[1]}-{parts[2]}"  # 26APR030600-00
        return ticker
    
    def _get_mid_price(self, yes_bid: float, yes_ask: float) -> float:
        """Calculate midpoint price from bid/ask."""
        if yes_bid > 0 and yes_ask > 0:
            return (yes_bid + yes_ask) / 2
        elif yes_bid > 0:
            return yes_bid
        elif yes_ask > 0:
            return yes_ask
        return 0.50  # Default to midpoint
    
    def _detect_cross(self, tracking: MarketTracking, yes_bid: float, yes_ask: float) -> Optional[str]:
        """
        Detect if price just crossed $0.50.
        Returns "up" if crossed up through midpoint, "down" if crossed down, None if no cross.
        """
        mid = self._get_mid_price(yes_bid, yes_ask)
        current_second = tracking.samples_above_50.__len__() + tracking.samples_below_50.__len__()
        
        if tracking.first_cross_direction is not None:
            # Already detected first cross, no need to check again
            return None
        
        if mid > MIDPOINT:
            tracking.samples_above_50.add(current_second)
        else:
            tracking.samples_below_50.add(current_second)
        
        # Check if we have samples on both sides
        if len(tracking.samples_above_50) > 0 and len(tracking.samples_below_50) > 0:
            # First cross detected!
            # Determine direction based on which sample came first
            min_above = min(tracking.samples_above_50) if tracking.samples_above_50 else float('inf')
            min_below = min(tracking.samples_below_50) if tracking.samples_below_50 else float('inf')
            
            if min_below < min_above:
                # Was below first, then went above = cross UP
                tracking.first_cross_direction = "up"
            else:
                # Was above first, then went below = cross DOWN
                tracking.first_cross_direction = "down"
            
            tracking.first_cross_price = mid
            tracking.first_cross_ts = datetime.now(timezone.utc).isoformat()
            return tracking.first_cross_direction
        
        return None
    
    def _check_for_final_result(self, ticker: str) -> Optional[str]:
        """Check if a market is settled and return result."""
        result = self.api.get_market_result(ticker)
        return result  # Returns 'yes', 'no', or None
    
    def poll_markets(self):
        """Poll all coin series for markets and track crosses."""
        self.poll_count += 1
        
        for coin in COINS:
            series_ticker = SERIES_TICKERS.get(coin)
            if not series_ticker:
                continue
            
            # Get open markets for this series
            markets = self.api.get_open_markets(series_ticker)
            
            # Also check if any tracked markets for this series are now closed
            for ticker, tracking in list(self.tracked_markets.items()):
                if tracking.coin != coin or tracking.finalized:
                    continue
                
                # Check if this market is still in the open markets list
                still_open = any(m.ticker == ticker for m in markets)
                
                if not still_open:
                    # Market may have closed - check for result
                    result = self._check_for_final_result(ticker)
                    if result is not None:
                        self._finalize_market(tracking, result)
        
        # Also periodically check closed markets for any we might have missed
        # Do this every 10 polls to avoid excessive API calls
        if self.poll_count % 10 == 0:
            self._check_closed_markets()
    
    def _check_closed_markets(self):
        """Check if any tracked markets have closed."""
        for ticker, tracking in list(self.tracked_markets.items()):
            if tracking.finalized:
                continue
            
            # Check if market is still open
            result = self.api.get_market_result(ticker)
            if result is not None:
                self._finalize_market(tracking, result)
    
    def _finalize_market(self, tracking: MarketTracking, result: str):
        """Finalize tracking data when market closes."""
        tracking.finalized = True
        
        # Get final price from the result
        # Result is 'yes' or 'no' - YES closing above 0.50 = YES won
        if result == 'yes':
            tracking.final_direction = "up"
            tracking.final_price = 1.0  # YES at expiry = $1.00
        else:
            tracking.final_direction = "down"
            tracking.final_price = 0.0  # NO at expiry = YES = $0.00
        
        # Determine if prediction was correct
        if tracking.first_cross_direction is not None:
            tracking.correct = (tracking.first_cross_direction == tracking.final_direction)
        else:
            # No first cross detected - cannot evaluate
            tracking.correct = None
        
        # Save to file
        self._save_record(tracking)
        
        logger.info(
            f"🏁 FINALIZED {tracking.ticker} | "
            f"First cross: {tracking.first_cross_direction} @ ${tracking.first_cross_price or 0:.4f} | "
            f"Final: {tracking.final_direction} @ ${tracking.final_price:.2f} | "
            f"Correct: {tracking.correct}"
        )
        
        # Remove from active tracking
        del self.tracked_markets[tracking.ticker]
    
    def _save_record(self, tracking: MarketTracking):
        """Save tracking record to JSON file."""
        record = {
            "timestamp": tracking.first_cross_ts or datetime.now(timezone.utc).isoformat(),
            "coin": tracking.coin,
            "ticker": tracking.ticker,
            "market_time": tracking.market_time,
            "first_cross": tracking.first_cross_direction,
            "first_cross_price": tracking.first_cross_price,
            "final_price": tracking.final_price,
            "final_direction": tracking.final_direction,
            "correct": tracking.correct
        }
        
        # Load existing data
        records = []
        if self.output_file.exists():
            try:
                with open(self.output_file, 'r') as f:
                    content = f.read().strip()
                    if content:
                        records = json.loads(content)
                        if not isinstance(records, list):
                            records = [records]
            except (json.JSONDecodeError, FileNotFoundError):
                records = []
        
        # Check for duplicate
        existing_idx = None
        for i, r in enumerate(records):
            if r.get('ticker') == tracking.ticker:
                existing_idx = i
                break
        
        if existing_idx is not None:
            # Update existing record
            records[existing_idx] = record
        else:
            # Add new record
            records.append(record)
        
        # Save
        with open(self.output_file, 'w') as f:
            json.dump(records, f, indent=2)
    
    def process_market(self, ticker: str, yes_bid: float, yes_ask: float):
        """Process a single market sample."""
        if ticker in self.existing_tickers and ticker not in self.tracked_markets:
            # Already processed this market
            return
        
        if ticker not in self.tracked_markets:
            # Start tracking new market
            coin = self._extract_coin(ticker)
            market_time = self._extract_market_time(ticker)
            tracking = MarketTracking(
                coin=coin,
                ticker=ticker,
                market_time=market_time,
                started_tracking=True
            )
            self.tracked_markets[ticker] = tracking
            logger.debug(f"📊 Started tracking {ticker} ({coin})")
        
        # Detect cross
        tracking = self.tracked_markets[ticker]
        cross = self._detect_cross(tracking, yes_bid, yes_ask)
        
        if cross:
            logger.info(
                f"🚦 FIRST CROSS {tracking.ticker} | "
                f"Direction: {cross} | Price: ${tracking.first_cross_price:.4f}"
            )
    
    def get_accuracy_stats(self) -> Dict:
        """Calculate accuracy statistics by coin."""
        if not self.output_file.exists():
            return {}
        
        try:
            with open(self.output_file, 'r') as f:
                records = json.load(f)
                if not isinstance(records, list):
                    records = [records]
        except (json.JSONDecodeError, FileNotFoundError):
            return {}
        
        # Calculate stats by coin
        stats = {}
        for coin in COINS:
            coin_records = [r for r in records if r.get('coin') == coin and r.get('correct') is not None]
            if coin_records:
                total = len(coin_records)
                correct = sum(1 for r in coin_records if r.get('correct'))
                stats[coin] = {
                    "total": total,
                    "correct": correct,
                    "accuracy": correct / total if total > 0 else 0,
                    "cross_up_correct": sum(1 for r in coin_records if r.get('first_cross') == 'up' and r.get('correct')),
                    "cross_down_correct": sum(1 for r in coin_records if r.get('first_cross') == 'down' and r.get('correct')),
                    "cross_up_total": sum(1 for r in coin_records if r.get('first_cross') == 'up'),
                    "cross_down_total": sum(1 for r in coin_records if r.get('first_cross') == 'down'),
                }
        
        return stats
    
    def print_stats(self):
        """Print accuracy statistics."""
        stats = self.get_accuracy_stats()
        
        logger.info("=" * 60)
        logger.info("📊 FIRST CROSS ACCURACY STATS")
        logger.info("=" * 60)
        
        if not stats:
            logger.info("No data yet...")
            return
        
        for coin, s in sorted(stats.items()):
            up_acc = s['cross_up_correct'] / s['cross_up_total'] if s['cross_up_total'] > 0 else 0
            down_acc = s['cross_down_correct'] / s['cross_down_total'] if s['cross_down_total'] > 0 else 0
            logger.info(
                f"  {coin}: {s['accuracy']:.1%} accuracy ({s['correct']}/{s['total']}) | "
                f"UP: {up_acc:.1%} ({s['cross_up_correct']}/{s['cross_up_total']}) | "
                f"DOWN: {down_acc:.1%} ({s['cross_down_correct']}/{s['cross_down_total']})"
            )
        
        logger.info("=" * 60)
    
    def run(self):
        """Main tracking loop."""
        logger.info("🚀 First Cross Tracker starting main loop...")
        
        try:
            while True:
                try:
                    # Poll all markets
                    self.poll_markets()
                    
                    # Get current prices for all tracked markets
                    for coin in COINS:
                        series_ticker = SERIES_TICKERS.get(coin)
                        if not series_ticker:
                            continue
                        
                        markets = self.api.get_open_markets(series_ticker)
                        for market in markets:
                            self.process_market(market.ticker, market.yes_bid, market.yes_ask)
                    
                    # Print stats every 60 polls (~2 minutes)
                    if self.poll_count % 60 == 0 and self.poll_count > 0:
                        self.print_stats()
                    
                    time.sleep(POLL_INTERVAL_SEC)
                    
                except KeyboardInterrupt:
                    logger.info("⏹️ First Cross Tracker shutting down...")
                    break
                except Exception as e:
                    logger.error(f"❌ Error in tracking loop: {e}")
                    time.sleep(5)
                    
        except KeyboardInterrupt:
            pass
        
        # Final stats
        self.print_stats()
        logger.info("👋 First Cross Tracker done!")


def main():
    """Entry point."""
    tracker = FirstCrossTracker()
    tracker.run()


if __name__ == "__main__":
    main()
