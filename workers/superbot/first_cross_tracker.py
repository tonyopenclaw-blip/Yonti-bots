#!/usr/bin/env python3
"""
🎯 Target Cross Tracker - Non-invasive market prediction analyzer
Tracks TWO first-cross signals per market:
1. Actual coin price crossing through the Kalshi TARGET PRICE (floor_strike)
2. YES price crossing through $0.50 midpoint

Both signals are tracked independently and compared to final outcome.

Example data structure:
{
  "timestamp": "2026-04-03T12:00:00+00:00",
  "coin": "BTC",
  "market": "26APR030600-00",
  "target_price": 66920.50,
  
  "yes_first_cross": "up",           // NEW: YES crossing $0.50 first
  "yes_cross_price": 0.501,         // NEW: YES price at cross
  "yes_cross_time": "13:01:23",     // NEW: timestamp of YES cross
  
  "coin_first_cross": "up",         // existing: coin crossing target first
  "coin_price_at_cross": 66920.50,  // Existing: coin price at target cross
  
  "coin_price_at_yes_cross": 66744.09,  // NEW: coin price when YES crossed $0.50
  
  "final_yes_price": 0.72,
  "final_coin_price": 67050.00,
  "yes_won": true,
  
  "analysis": {
    "yes_cross_correct": true,    // did YES crossing $0.50 predict outcome?
    "coin_cross_correct": true    // did coin crossing target predict outcome?
  }
}

Non-invasive: runs alongside Superbot/Recorder without affecting trading behavior.
"""

import json
import logging
import os
import sys
import time
import requests
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Set
from dataclasses import dataclass, asdict

# Add parent dir to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from config import (
    KALSHI_ACCESS_KEY, KALSHI_TRACKER_KEY, COINS, SERIES_TICKERS,
    LOG_DIR, LOG_LEVEL, LOG_FORMAT, LOG_DATE_FORMAT
)
from kalshi_api import KalshiAPI

# =============================================================================
# COINBASE API FOR ACTUAL PRICES
# =============================================================================
COINBASE_API = "https://api.exchange.coinbase.com"
COINBASE_PRODUCTS = {
    "BTC": "BTC-USD",
    "ETH": "ETH-USD",
    "SOL": "SOL-USD",
    "BNB": "BNB-USD",
    "DOGE": "DOGE-USD",
    "XRP": "XRP-USD",
    "HYPE": "HYPE-USD",
    "ADA": "ADA-USD",
}

def get_coinbase_price(coin: str) -> Optional[float]:
    """
    Fetch the current price for a coin from Coinbase Exchange API.
    Returns the latest trade price or None if fetch fails.
    """
    product_id = COINBASE_PRODUCTS.get(coin.upper())
    if not product_id:
        return None
    
    try:
        url = f"{COINBASE_API}/products/{product_id}/ticker"
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        price = float(data.get('price', 0))
        return price
    except Exception as e:
        logger.warning(f"Failed to fetch Coinbase price for {coin}: {e}")
        return None

def get_all_coinbase_prices() -> Dict[str, float]:
    """Fetch current prices for all coins."""
    prices = {}
    for coin in COINS:
        price = get_coinbase_price(coin)
        if price is not None:
            prices[coin] = price
    return prices

# =============================================================================
# LOGGING SETUP
# =============================================================================
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "target_cross_tracker.log"

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
OUTPUT_FILE = Path(__file__).parent / "target_cross_data.json"
POLL_INTERVAL_SEC = 2  # Poll every 2 seconds for active markets

# Midpoint threshold for YES price
MIDPOINT = 0.50


@dataclass
class MarketTracking:
    """Tracks first cross data for a single market through the target price AND YES $0.50 midpoint."""
    coin: str
    ticker: str
    market_time: str  # Series ticker like "26APR030600-00"
    target_price: float  # floor_strike from Kalshi - the target level to track
    
    # --- YES $0.50 midpoint crossing (NEW) ---
    yes_first_cross: Optional[str] = None  # "up" or "down" through $0.50
    yes_cross_price: Optional[float] = None  # YES price at cross
    yes_cross_time: Optional[str] = None  # HH:MM:SS timestamp of YES cross
    coin_price_at_yes_cross: Optional[float] = None  # Coin price when YES crossed $0.50
    yes_samples_above: list = None  # List of (timestamp, yes_price) when YES > $0.50
    yes_samples_below: list = None  # List of (timestamp, yes_price) when YES < $0.50
    
    # --- Coin target crossing (existing) ---
    first_cross_direction: Optional[str] = None  # "up" or "down" through target
    first_cross_ts: Optional[str] = None  # ISO timestamp of first cross
    coin_price_at_cross: Optional[float] = None  # Actual coin price when crossed target
    samples_above_target: list = None  # List of (timestamp, price) when above target
    samples_below_target: list = None  # List of (timestamp, price) when below target
    
    started_tracking: bool = False
    finalized: bool = False
    final_coin_price: Optional[float] = None  # Actual coin price at series expiry
    final_yes_price: Optional[float] = None  # YES price at series expiry
    yes_won: Optional[bool] = None  # Did YES win?
    analysis: Optional[Dict] = None  # Prediction accuracy analysis
    
    _start_ts: float = None  # Wall-clock time when tracking started
    
    def __post_init__(self):
        if self.yes_samples_above is None:
            self.yes_samples_above = []
        if self.yes_samples_below is None:
            self.yes_samples_below = []
        if self.samples_above_target is None:
            self.samples_above_target = []
        if self.samples_below_target is None:
            self.samples_below_target = []
        if self._start_ts is None:
            self._start_ts = time.time()
        if self.analysis is None:
            self.analysis = {}


class TargetCrossTracker:
    """
    Tracks TWO first-cross signals per market:
    1. Actual crypto price crossing through the TARGET PRICE (floor_strike)
    2. YES price crossing through $0.50 midpoint
    
    Both signals are tracked independently and compared to final outcome.
    
    Non-invasive: Only reads data, never trades.
    Runs alongside Superbot/Recorder to collect prediction accuracy stats.
    """
    
    def __init__(self):
        self.api = KalshiAPI(access_key=KALSHI_TRACKER_KEY)
        self.tracked_markets: Dict[str, MarketTracking] = {}
        self.output_file = OUTPUT_FILE
        self.poll_count = 0
        
        # Load existing data to avoid duplicates
        self.existing_tickers: Set[str] = set()
        self._load_existing_data()
        
        logger.info("=" * 60)
        logger.info("🎯 TARGET CROSS TRACKER INITIALIZED!")
        logger.info("Tracking TWO signals per market:")
        logger.info("  1. Coin price crossing Kalshi TARGET (floor_strike)")
        logger.info("  2. YES price crossing $0.50 midpoint")
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
                        self.existing_tickers = {r.get('market', '').replace('_', '-') for r in data if r.get('market')}
                logger.info(f"Loaded {len(self.existing_tickers)} existing market records")
            except json.JSONDecodeError:
                logger.warning("Could not parse existing target_cross_data.json")
    
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
    
    def _get_floor_strike(self, ticker: str) -> Optional[float]:
        """
        Fetch the floor_strike (target price) for a market from raw API response.
        Returns None if not available.
        """
        result = self.api._get(f"/markets/{ticker}")
        if "error" in result:
            return None
        
        market_data = result.get("market", {})
        if not market_data:
            return None
        
        # floor_strike is the target price for the market
        floor_strike = market_data.get("floor_strike")
        if floor_strike is not None:
            return float(floor_strike)
        
        # Fallback: try to parse from yes_sub_title if available
        yes_sub_title = market_data.get("yes_sub_title", "")
        if "Target Price:" in yes_sub_title:
            import re
            match = re.search(r'\$?([\d,]+\.?\d*)', yes_sub_title)
            if match:
                price_str = match.group(1).replace(',', '')
                return float(price_str)
        
        return None
    
    def _get_yes_price(self, ticker: str) -> Optional[float]:
        """
        Fetch the current YES price for a market from the API.
        Returns price between 0.00-1.00 or None if not available.
        """
        result = self.api._get(f"/markets/{ticker}")
        if "error" in result:
            return None
        
        market_data = result.get("market", {})
        if not market_data:
            return None
        
        # Get YES bid/ask to calculate midpoint
        yes_bid = market_data.get("yes_bid")
        yes_ask = market_data.get("yes_ask")
        
        if yes_bid is not None and yes_ask is not None:
            return (float(yes_bid) + float(yes_ask)) / 2.0
        
        # Fallback to yes_price if available
        yes_price = market_data.get("yes_price")
        if yes_price is not None:
            return float(yes_price)
        
        return None
    
    def _get_market_result(self, ticker: str) -> Optional[str]:
        """Check if market settled and return result."""
        result = self.api._get(f"/markets/{ticker}")
        if "error" in result:
            return None
        
        market_data = result.get("market", {})
        status = market_data.get("status", "")
        if status == "settled":
            return market_data.get("result", None)  # 'yes' or 'no'
        return None
    
    def _detect_yes_cross_through_midpoint(
        self, 
        tracking: MarketTracking, 
        yes_price: float,
        coin_price: float
    ) -> Optional[str]:
        """
        Detect if YES price just crossed through $0.50 midpoint.
        Returns "up" if crossed up through $0.50, "down" if crossed down, None if no cross.
        
        NEW: Also record coin price at the moment of YES cross.
        """
        current_ts = time.time()
        current_time_str = datetime.now(timezone.utc).strftime("%H:%M:%S")
        
        if tracking.yes_first_cross is not None:
            # Already detected first YES cross
            return None
        
        if yes_price > MIDPOINT:
            tracking.yes_samples_above.append((current_ts, yes_price))
        else:
            tracking.yes_samples_below.append((current_ts, yes_price))
        
        # Check if we have samples on both sides
        if len(tracking.yes_samples_above) > 0 and len(tracking.yes_samples_below) > 0:
            # First YES cross detected!
            first_above = min(ts for ts, _ in tracking.yes_samples_above)
            first_below = min(ts for ts, _ in tracking.yes_samples_below)
            
            if first_below < first_above:
                # Was below first, then went above = cross UP through $0.50
                tracking.yes_first_cross = "up"
            else:
                # Was above first, then went below = cross DOWN through $0.50
                tracking.yes_first_cross = "down"
            
            tracking.yes_cross_time = current_time_str
            tracking.yes_cross_price = yes_price
            tracking.coin_price_at_yes_cross = coin_price
            
            logger.info(
                f"💰 YES CROSS {tracking.ticker} | "
                f"Direction: {tracking.yes_first_cross} | "
                f"YES: ${yes_price:.3f} | "
                f"Coin: ${coin_price:,.2f} | "
                f"Time: {tracking.yes_cross_time}"
            )
            
            return tracking.yes_first_cross
        
        return None
    
    def _detect_cross_through_target(
        self, 
        tracking: MarketTracking, 
        coin_price: float
    ) -> Optional[str]:
        """
        Detect if coin price just crossed through the target price.
        Returns "up" if crossed up through target, "down" if crossed down, None if no cross.
        """
        current_ts = time.time()
        target = tracking.target_price
        
        if tracking.first_cross_direction is not None:
            # Already detected first cross
            return None
        
        if coin_price > target:
            tracking.samples_above_target.append((current_ts, coin_price))
        else:
            tracking.samples_below_target.append((current_ts, coin_price))
        
        # Check if we have samples on both sides
        if len(tracking.samples_above_target) > 0 and len(tracking.samples_below_target) > 0:
            # First cross detected!
            first_above = min(ts for ts, _ in tracking.samples_above_target)
            first_below = min(ts for ts, _ in tracking.samples_below_target)
            
            if first_below < first_above:
                # Was below first, then went above = cross UP through target
                tracking.first_cross_direction = "up"
            else:
                # Was above first, then went below = cross DOWN through target
                tracking.first_cross_direction = "down"
            
            tracking.first_cross_ts = datetime.now(timezone.utc).isoformat()
            tracking.coin_price_at_cross = coin_price
            
            logger.info(
                f"🚦 COIN CROSS {tracking.ticker} | "
                f"Direction: {tracking.first_cross_direction} | "
                f"Target: ${target:,.2f} | "
                f"Coin Price: ${coin_price:,.2f}"
            )
            
            return tracking.first_cross_direction
        
        return None
    
    def poll_markets(self):
        """Poll all coin series for markets and track crosses."""
        self.poll_count += 1
        
        # First, get current coin prices
        coin_prices = get_all_coinbase_prices()
        
        for coin in COINS:
            series_ticker = SERIES_TICKERS.get(coin)
            if not series_ticker:
                continue
            
            coin_price = coin_prices.get(coin)
            
            # Get open markets for this series
            markets = self.api.get_open_markets(series_ticker)
            
            for market in markets:
                ticker = market.ticker
                
                # Skip if already finalized
                if ticker in self.tracked_markets and self.tracked_markets[ticker].finalized:
                    continue
                
                # Skip if already processed
                if ticker in self.existing_tickers and ticker not in self.tracked_markets:
                    continue
                
                # Start tracking if new market
                if ticker not in self.tracked_markets:
                    # Get floor_strike from raw API response
                    floor_strike = self._get_floor_strike(ticker)
                    
                    if floor_strike is None:
                        logger.debug(f"Could not get floor_strike for {ticker}, skipping")
                        continue
                    
                    market_time = self._extract_market_time(ticker)
                    tracking = MarketTracking(
                        coin=coin,
                        ticker=ticker,
                        market_time=market_time,
                        target_price=floor_strike,
                        started_tracking=True
                    )
                    self.tracked_markets[ticker] = tracking
                    logger.info(
                        f"📊 Started tracking {ticker} | "
                        f"{coin} target: ${floor_strike:,.2f}"
                    )
                
                # Process YES price cross detection (NEW)
                tracking = self.tracked_markets[ticker]
                yes_price = self._get_yes_price(ticker)
                if yes_price is not None and coin_price is not None:
                    self._detect_yes_cross_through_midpoint(tracking, yes_price, coin_price)
                
                # Process coin price cross detection (existing)
                if coin_price is not None:
                    self._detect_cross_through_target(tracking, coin_price)
        
        # Check for closed markets every 10 polls
        if self.poll_count % 10 == 0:
            self._check_closed_markets()
    
    def _check_closed_markets(self):
        """Check if any tracked markets have closed."""
        for ticker, tracking in list(self.tracked_markets.items()):
            if tracking.finalized:
                continue
            
            result = self._get_market_result(ticker)
            if result is not None:
                self._finalize_market(tracking, result)
    
    def _finalize_market(self, tracking: MarketTracking, result: str):
        """Finalize tracking data when market closes."""
        tracking.finalized = True
        
        # YES won means price ended up ABOVE target
        # NO won means price ended up BELOW target
        tracking.yes_won = (result == 'yes')
        
        # Get final coin price
        final_price = get_coinbase_price(tracking.coin)
        if final_price:
            tracking.final_coin_price = final_price
        
        # Get final YES price
        final_yes = self._get_yes_price(tracking.ticker)
        if final_yes is not None:
            tracking.final_yes_price = final_yes
        
        # Analyze YES $0.50 cross prediction (NEW)
        if tracking.yes_first_cross is not None:
            if tracking.yes_first_cross == "up":
                # YES crossed up through $0.50 -> predicts YES will win
                tracking.analysis["yes_cross_correct"] = tracking.yes_won == True
            else:  # "down"
                # YES crossed down through $0.50 -> predicts NO will win
                tracking.analysis["yes_cross_correct"] = tracking.yes_won == False
        else:
            tracking.analysis["yes_cross_correct"] = None
        
        # Analyze coin target cross prediction (existing)
        if tracking.first_cross_direction is not None:
            if tracking.first_cross_direction == "up":
                # Crossed up first means we expect YES to win (price above target)
                tracking.analysis["coin_cross_correct"] = tracking.yes_won == True
            else:  # "down"
                # Crossed down first means we expect NO to win (price below target)
                tracking.analysis["coin_cross_correct"] = tracking.yes_won == False
        else:
            tracking.analysis["coin_cross_correct"] = None
        
        # Save to file
        self._save_record(tracking)
        
        logger.info(
            f"🏁 FINALIZED {tracking.ticker} | "
            f"YES cross: {tracking.yes_first_cross or 'N/A'} @ {tracking.yes_cross_time or 'N/A'} | "
            f"Coin cross: {tracking.first_cross_direction or 'N/A'} @ ${tracking.coin_price_at_cross or 0:,.2f} | "
            f"YES {'WON' if tracking.yes_won else 'LOST'} | "
            f"YES cross correct: {tracking.analysis.get('yes_cross_correct')} | "
            f"Coin cross correct: {tracking.analysis.get('coin_cross_correct')}"
        )
        
        # Remove from active tracking
        del self.tracked_markets[tracking.ticker]
    
    def _save_record(self, tracking: MarketTracking):
        """Save tracking record to JSON file."""
        record = {
            "timestamp": tracking.first_cross_ts or datetime.now(timezone.utc).isoformat(),
            "coin": tracking.coin,
            "market": tracking.market_time,  # e.g., "26APR030600-00"
            "target_price": tracking.target_price,
            
            # NEW: YES $0.50 midpoint crossing
            "yes_first_cross": tracking.yes_first_cross,
            "yes_cross_price": tracking.yes_cross_price,
            "yes_cross_time": tracking.yes_cross_time,
            "coin_price_at_yes_cross": tracking.coin_price_at_yes_cross,
            
            # Existing: Coin target crossing
            "coin_first_cross": tracking.first_cross_direction,
            "coin_price_at_cross": tracking.coin_price_at_cross,
            
            # Final state
            "final_yes_price": tracking.final_yes_price,
            "final_coin_price": tracking.final_coin_price,
            "yes_won": tracking.yes_won,
            
            # Analysis
            "analysis": {
                "yes_cross_correct": tracking.analysis.get("yes_cross_correct"),
                "coin_cross_correct": tracking.analysis.get("coin_cross_correct"),
            },
            
            "notes": (
                f"YES crossed {'UP' if tracking.yes_first_cross == 'up' else 'DOWN' if tracking.yes_first_cross == 'down' else 'NEITHER'} "
                f"through $0.50 first at {tracking.yes_cross_time or 'N/A'}; "
                f"{tracking.coin} crossed {'UP' if tracking.first_cross_direction == 'up' else 'DOWN' if tracking.first_cross_direction == 'down' else 'NEITHER'} "
                f"through target ${tracking.target_price:,.2f} at {tracking.first_cross_ts or 'N/A'}"
            )
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
        
        # Check for duplicate by market_time + coin (more stable than full ticker)
        existing_idx = None
        record_key = f"{tracking.coin}_{tracking.market_time}"
        for i, r in enumerate(records):
            r_key = f"{r.get('coin', '')}_{r.get('market', '')}"
            if r_key == record_key:
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
            coin_records = [
                r for r in records 
                if r.get('coin') == coin and r.get('analysis', {}).get('coin_cross_correct') is not None
            ]
            if coin_records:
                total = len(coin_records)
                coin_correct = sum(1 for r in coin_records if r.get('analysis', {}).get('coin_cross_correct'))
                
                # YES cross stats (NEW)
                yes_cross_records = [r for r in coin_records if r.get('yes_first_cross') is not None]
                yes_cross_correct = sum(1 for r in yes_cross_records if r.get('analysis', {}).get('yes_cross_correct'))
                
                # Coin cross breakdown
                cross_up_records = [r for r in coin_records if r.get('coin_first_cross') == 'up']
                cross_down_records = [r for r in coin_records if r.get('coin_first_cross') == 'down']
                
                cross_up_correct = sum(1 for r in cross_up_records if r.get('analysis', {}).get('coin_cross_correct'))
                cross_down_correct = sum(1 for r in cross_down_records if r.get('analysis', {}).get('coin_cross_correct'))
                
                # YES cross breakdown (NEW)
                yes_up_records = [r for r in yes_cross_records if r.get('yes_first_cross') == 'up']
                yes_down_records = [r for r in yes_cross_records if r.get('yes_first_cross') == 'down']
                yes_up_correct = sum(1 for r in yes_up_records if r.get('analysis', {}).get('yes_cross_correct'))
                yes_down_correct = sum(1 for r in yes_down_records if r.get('analysis', {}).get('yes_cross_correct'))
                
                stats[coin] = {
                    "total": total,
                    "coin_cross_correct": coin_correct,
                    "coin_cross_accuracy": coin_correct / total if total > 0 else 0,
                    "yes_cross_correct": yes_cross_correct,
                    "yes_cross_total": len(yes_cross_records),
                    "yes_cross_accuracy": yes_cross_correct / len(yes_cross_records) if yes_cross_records else 0,
                    "coin_cross_up_correct": cross_up_correct,
                    "coin_cross_up_total": len(cross_up_records),
                    "coin_cross_down_correct": cross_down_correct,
                    "coin_cross_down_total": len(cross_down_records),
                    "yes_cross_up_correct": yes_up_correct,
                    "yes_cross_up_total": len(yes_up_records),
                    "yes_cross_down_correct": yes_down_correct,
                    "yes_cross_down_total": len(yes_down_records),
                }
        
        return stats
    
    def print_stats(self):
        """Print accuracy statistics."""
        stats = self.get_accuracy_stats()
        
        logger.info("=" * 60)
        logger.info("🎯 TARGET CROSS ACCURACY STATS")
        logger.info("Tracking TWO signals per market:")
        logger.info("  1. Coin price crossing through TARGET (floor_strike)")
        logger.info("  2. YES price crossing through $0.50 midpoint")
        logger.info("=" * 60)
        
        if not stats:
            logger.info("No data yet...")
            return
        
        for coin, s in sorted(stats.items()):
            logger.info(f"  {coin}:")
            logger.info(f"    COIN CROSS: {s['coin_cross_accuracy']:.1%} ({s['coin_cross_correct']}/{s['total']})")
            if s['coin_cross_up_total'] > 0:
                up_acc = s['coin_cross_up_correct'] / s['coin_cross_up_total']
                logger.info(f"      UP:   {up_acc:.1%} ({s['coin_cross_up_correct']}/{s['coin_cross_up_total']})")
            if s['coin_cross_down_total'] > 0:
                down_acc = s['coin_cross_down_correct'] / s['coin_cross_down_total']
                logger.info(f"      DOWN: {down_acc:.1%} ({s['coin_cross_down_correct']}/{s['coin_cross_down_total']})")
            
            logger.info(f"    YES CROSS: {s['yes_cross_accuracy']:.1%} ({s['yes_cross_correct']}/{s['yes_cross_total']})")
            if s['yes_cross_up_total'] > 0:
                yes_up_acc = s['yes_cross_up_correct'] / s['yes_cross_up_total']
                logger.info(f"      UP:   {yes_up_acc:.1%} ({s['yes_cross_up_correct']}/{s['yes_cross_up_total']})")
            if s['yes_cross_down_total'] > 0:
                yes_down_acc = s['yes_cross_down_correct'] / s['yes_cross_down_total']
                logger.info(f"      DOWN: {yes_down_acc:.1%} ({s['yes_cross_down_correct']}/{s['yes_cross_down_total']})")
        
        logger.info("=" * 60)
    
    def run(self):
        """Main tracking loop."""
        logger.info("🚀 Target Cross Tracker starting main loop...")
        
        try:
            while True:
                try:
                    self.poll_markets()
                    
                    # Print stats every 60 polls (~2 minutes)
                    if self.poll_count % 60 == 0 and self.poll_count > 0:
                        self.print_stats()
                    
                    time.sleep(POLL_INTERVAL_SEC)
                    
                except KeyboardInterrupt:
                    logger.info("⏹️ Target Cross Tracker shutting down...")
                    break
                except Exception as e:
                    logger.error(f"❌ Error in tracking loop: {e}")
                    time.sleep(5)
                    
        except KeyboardInterrupt:
            pass
        
        # Final stats
        self.print_stats()
        logger.info("👋 Target Cross Tracker done!")


def main():
    """Entry point."""
    tracker = TargetCrossTracker()
    tracker.run()


if __name__ == "__main__":
    main()
