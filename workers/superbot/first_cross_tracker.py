#!/usr/bin/env python3
"""
🎯 Target Cross Tracker v2 - Coin-based first cross detection

Tony's Architecture (Rate-Limit Friendly):
1. **Kalshi hit: ONCE at open** — get target price (floor_strike) when market opens
2. **Track via Coinbase** — real-time coin price (BTC/ETH/SOL), detect when it crosses target (up/down)
3. **Track YES $0.50 via Kalshi** — poll every 30-60 seconds, stop polling after first cross + 2 confirmations
4. **Kalshi hit: ONCE at expiry** — get final resolution (YES won or not)

Target: Eliminate 429 rate limit errors by reducing Kalshi API calls from ~90/market to ~17/market.

Data structure per market:
- `target_price` — from Kalshi (floor_strike)
- `coin_first_cross` — "up"/"down"/null (from Coinbase)
- `coin_cross_price` — price at cross
- `yes_first_cross` — "up"/"down"/null (from Kalshi, minimal polling)
- `yes_cross_price` — YES price at cross
- `final_yes_price` — from Kalshi at expiry
- `yes_won` — final outcome
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
from dataclasses import dataclass, field

# Add parent dir to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from config import (
    KALSHI_ACCESS_KEY, KALSHI_TRACKER_KEY, COINS, SERIES_TICKERS,
    LOG_DIR, LOG_LEVEL, LOG_FORMAT, LOG_DATE_FORMAT
)
from kalshi_api import KalshiAPI

# =============================================================================
# COINBASE API FOR ACTUAL PRICES (real-time, no rate limits)
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
    """Fetch the current price for a coin from Coinbase Exchange API."""
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
        logger.warning(f"Coinbase price fetch failed for {coin}: {e}")
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

# Polling intervals - TONY'S ARCHITECTURE
COINBASE_POLL_INTERVAL_SEC = 5   # Poll Coinbase every 5 seconds (real-time tracking)
KALSHI_YES_POLL_INTERVAL_SEC = 30  # Poll Kalshi YES price every 30 seconds (not every 2 sec!)
SETTLEMENT_CHECK_INTERVAL_SEC = 60  # Check settlement once per minute

# Confirmation ticks needed after first cross detected
YES_CONFIRMATION_TICKS = 2

# Midpoint threshold for YES price
MIDPOINT = 0.50


@dataclass
class MarketTracking:
    """
    Tracks first cross data for a single market.
    
    Architecture:
    - target_price: fetched ONCE from Kalshi at market open
    - coin_first_cross: detected via Coinbase real-time polling
    - yes_first_cross: detected via minimal Kalshi polling (every 30s, stop after 2 confirmations)
    - final resolution: fetched ONCE from Kalshi at expiry
    """
    coin: str
    ticker: str
    market_time: str  # Series ticker like "26APR030600-00"
    target_price: float  # floor_strike from Kalshi - fetched ONCE at open
    
    # --- Coinbase-based target crossing ---
    coin_first_cross: Optional[str] = None  # "up" or "down" through target
    coin_cross_price: Optional[float] = None  # Coin price at target cross
    coin_cross_time: Optional[str] = None  # HH:MM:SS timestamp
    
    # --- Kalshi YES $0.50 midpoint crossing (minimal polling) ---
    yes_first_cross: Optional[str] = None  # "up" or "down" through $0.50
    yes_cross_price: Optional[float] = None  # YES price at cross
    yes_cross_time: Optional[str] = None  # HH:MM:SS timestamp
    coin_price_at_yes_cross: Optional[float] = None  # Coin price when YES crossed $0.50
    
    # --- State tracking for minimal polling ---
    started_tracking: bool = False
    coin_crossed: bool = False  # Coinbase cross detected
    yes_crossed: bool = False  # YES cross detected (Kalshi)
    yes_confirmations: int = 0  # Confirmation ticks after first YES cross
    yes_polling_stopped: bool = False  # Stop polling Kalshi after YES cross + confirmations
    
    # --- Final state (fetched at expiry) ---
    finalized: bool = False
    final_coin_price: Optional[float] = None
    final_yes_price: Optional[float] = None
    yes_won: Optional[bool] = None
    analysis: Optional[Dict] = field(default_factory=dict)
    
    # --- Sample tracking for cross detection ---
    _coin_samples_above: list = field(default_factory=list)
    _coin_samples_below: list = field(default_factory=list)
    _yes_samples_above: list = field(default_factory=list)
    _yes_samples_below: list = field(default_factory=list)
    
    # Tracking metadata
    _started_at: float = field(default_factory=time.time)
    _last_yes_poll_ts: float = field(default_factory=time.time)
    
    def __post_init__(self):
        if self.analysis is None:
            self.analysis = {}
    
    def should_poll_yes(self) -> bool:
        """Should we poll Kalshi for YES price? Only if YES hasn't crossed + confirmations."""
        if self.yes_polling_stopped:
            return False
        if self.yes_crossed and self.yes_confirmations >= YES_CONFIRMATION_TICKS:
            self.yes_polling_stopped = True
            return False
        return True


class TargetCrossTracker:
    """
    🎯 Target Cross Tracker v2 - Rate-Limit Friendly Edition
    
    Tony's Architecture:
    1. **Kalshi hit: ONCE at open** — get target price (floor_strike)
    2. **Track via Coinbase** — real-time coin price tracking every 5 seconds
    3. **Track YES via Kalshi** — poll every 30s, stop after cross + 2 confirmations
    4. **Kalshi hit: ONCE at expiry** — get final resolution
    
    Rate limit budget: ~32 calls/market vs current ~1000+
    """
    
    def __init__(self):
        self.api = KalshiAPI(access_key=KALSHI_TRACKER_KEY)
        self.tracked_markets: Dict[str, MarketTracking] = {}
        self.output_file = OUTPUT_FILE
        self.poll_count = 0
        
        # Track last poll times for smart polling
        self._last_coin_poll_ts = time.time()
        self._last_yes_poll_ts = time.time()  # Kalshi YES polling
        self._last_settlement_check_ts = time.time()
        
        # Load existing data to avoid duplicates
        self.existing_tickers: Set[str] = set()
        self._load_existing_data()
        
        logger.info("=" * 70)
        logger.info("🎯 TARGET CROSS TRACKER v2 INITIALIZED!")
        logger.info("Tony's Architecture - Rate-Limit Friendly:")
        logger.info("  1. Kalshi ONCE at open → get target price (floor_strike)")
        logger.info("  2. Coinbase every 5s → real-time coin price tracking")
        logger.info("  3. Kalshi every 30s → YES price (stop after cross + 2 confirmations)")
        logger.info("  4. Kalshi ONCE at expiry → final resolution")
        logger.info(f"Coins: {', '.join(COINS)}")
        logger.info(f"Output: {self.output_file}")
        logger.info(f"Existing records: {len(self.existing_tickers)} markets")
        logger.info("=" * 70)
    
    def _load_existing_data(self):
        """Load existing tickers to avoid duplicate entries."""
        if self.output_file.exists():
            try:
                with open(self.output_file, 'r') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self.existing_tickers = {
                            r.get('market', '').replace('_', '-') 
                            for r in data if r.get('market')
                        }
                logger.info(f"Loaded {len(self.existing_tickers)} existing market records")
            except json.JSONDecodeError:
                logger.warning("Could not parse existing target_cross_data.json")
    
    def _extract_market_time(self, ticker: str) -> str:
        """Extract market time from ticker like KXBTC15M-26APR030600-00"""
        parts = ticker.split("-")
        if len(parts) >= 3:
            return f"{parts[1]}-{parts[2]}"  # 26APR030600-00
        return ticker
    
    def _get_floor_strike(self, ticker: str) -> Optional[float]:
        """
        Fetch the floor_strike (target price) for a market.
        Called ONCE at market open.
        """
        result = self.api._get(f"/markets/{ticker}")
        if "error" in result:
            logger.warning(f"Failed to get floor_strike for {ticker}: {result['error']}")
            return None
        
        market_data = result.get("market", {})
        floor_strike = market_data.get("floor_strike")
        if floor_strike is not None:
            return float(floor_strike)
        
        # Fallback: parse from yes_sub_title
        import re
        yes_sub_title = market_data.get("yes_sub_title", "")
        if "Target Price:" in yes_sub_title:
            match = re.search(r'\$?([\d,]+\.?\d*)', yes_sub_title)
            if match:
                return float(match.group(1).replace(',', ''))
        
        return None
    
    def _get_yes_price(self, ticker: str) -> Optional[float]:
        """
        Fetch the current YES price for a market.
        Called minimally - only every 30s for markets not yet crossed.
        """
        result = self.api._get(f"/markets/{ticker}")
        if "error" in result:
            return None
        
        market_data = result.get("market", {})
        
        yes_bid = market_data.get("yes_bid")
        yes_ask = market_data.get("yes_ask")
        
        if yes_bid is not None and yes_ask is not None:
            return (float(yes_bid) + float(yes_ask)) / 2.0
        
        yes_price = market_data.get("yes_price")
        if yes_price is not None:
            return float(yes_price)
        
        return None
    
    def _get_market_result(self, ticker: str) -> Optional[str]:
        """
        Check if market settled and return result.
        Called ONCE at expiry.
        """
        result = self.api._get(f"/markets/{ticker}")
        if "error" in result:
            return None
        
        market_data = result.get("market", {})
        status = market_data.get("status", "")
        if status == "settled":
            return market_data.get("result", None)
        return None
    
    def _detect_coin_cross(self, tracking: MarketTracking, coin_price: float) -> Optional[str]:
        """
        Detect if coin price crossed through the target price via Coinbase.
        Returns "up", "down", or None.
        """
        current_ts = time.time()
        target = tracking.target_price
        
        if tracking.coin_crossed:
            return None
        
        if coin_price > target:
            tracking._coin_samples_above.append((current_ts, coin_price))
        else:
            tracking._coin_samples_below.append((current_ts, coin_price))
        
        # Check if we have samples on both sides
        if len(tracking._coin_samples_above) > 0 and len(tracking._coin_samples_below) > 0:
            first_above = min(ts for ts, _ in tracking._coin_samples_above)
            first_below = min(ts for ts, _ in tracking._coin_samples_below)
            
            if first_below < first_above:
                direction = "up"
            else:
                direction = "down"
            
            tracking.coin_first_cross = direction
            tracking.coin_cross_price = coin_price
            tracking.coin_cross_time = datetime.now(timezone.utc).strftime("%H:%M:%S")
            tracking.coin_crossed = True
            
            logger.info(
                f"🚦 COIN CROSS {tracking.ticker} | "
                f"Direction: {direction} | "
                f"Target: ${target:,.2f} | "
                f"Coin Price: ${coin_price:,.2f}"
            )
            return direction
        
        return None
    
    def _detect_yes_cross(
        self, 
        tracking: MarketTracking, 
        yes_price: float,
        coin_price: float
    ) -> Optional[str]:
        """
        Detect if YES price crossed through $0.50 midpoint.
        Returns "up", "down", or None.
        Only call this every 30s for markets that haven't crossed yet.
        """
        current_ts = time.time()
        
        if tracking.yes_crossed:
            # Already detected first cross - count confirmations
            tracking.yes_confirmations += 1
            logger.debug(
                f"YES confirm {tracking.yes_confirmations}/{YES_CONFIRMATION_TICKS} "
                f"for {tracking.ticker} @ ${yes_price:.3f}"
            )
            return None
        
        if yes_price > MIDPOINT:
            tracking._yes_samples_above.append((current_ts, yes_price))
        else:
            tracking._yes_samples_below.append((current_ts, yes_price))
        
        # Check if we have samples on both sides
        if len(tracking._yes_samples_above) > 0 and len(tracking._yes_samples_below) > 0:
            first_above = min(ts for ts, _ in tracking._yes_samples_above)
            first_below = min(ts for ts, _ in tracking._yes_samples_below)
            
            if first_below < first_above:
                direction = "up"
            else:
                direction = "down"
            
            tracking.yes_first_cross = direction
            tracking.yes_cross_price = yes_price
            tracking.yes_cross_time = datetime.now(timezone.utc).strftime("%H:%M:%S")
            tracking.coin_price_at_yes_cross = coin_price
            tracking.yes_crossed = True
            tracking.yes_confirmations = 1  # First detection = 1 confirmation
            
            logger.info(
                f"💰 YES CROSS {tracking.ticker} | "
                f"Direction: {direction} | "
                f"YES: ${yes_price:.3f} | "
                f"Coin: ${coin_price:,.2f} | "
                f"Time: {tracking.yes_cross_time}"
            )
            return direction
        
        return None
    
    def poll_markets(self):
        """
        Main polling loop - smart/rate-limit friendly.
        
        Architecture:
        - Coinbase: every 5 seconds (no rate limits, real-time)
        - Kalshi YES: every 30 seconds ONLY for markets not yet crossed
        - Settlement: every 60 seconds for markets approaching expiry
        """
        self.poll_count += 1
        current_ts = time.time()
        
        # === COINBASE POLLING (every 5 seconds) ===
        if current_ts - self._last_coin_poll_ts >= COINBASE_POLL_INTERVAL_SEC:
            self._last_coin_poll_ts = current_ts
            coin_prices = get_all_coinbase_prices()
            
            for coin, coin_price in coin_prices.items():
                self._process_coin_price(coin, coin_price)
        
        # === KALSHI YES POLLING (every 30 seconds, only for not-yet-crossed) ===
        if current_ts - self._last_yes_poll_ts >= KALSHI_YES_POLL_INTERVAL_SEC:
            self._last_yes_poll_ts = current_ts
            self._poll_yes_prices()
        
        # === SETTLEMENT CHECK (every 60 seconds) ===
        if current_ts - self._last_settlement_check_ts >= SETTLEMENT_CHECK_INTERVAL_SEC:
            self._last_settlement_check_ts = current_ts
            self._check_settlements()
    
    def _process_coin_price(self, coin: str, coin_price: float):
        """Process a coin price update for all tracked markets of that coin."""
        series_ticker = SERIES_TICKERS.get(coin)
        if not series_ticker:
            return
        
        # Get open markets for this series
        markets = self.api.get_open_markets(series_ticker)
        
        for market in markets:
            ticker = market.ticker
            
            # Skip if already finalized
            if ticker in self.tracked_markets and self.tracked_markets[ticker].finalized:
                continue
            
            # Skip if already processed (exists but not tracked)
            if ticker in self.existing_tickers and ticker not in self.tracked_markets:
                continue
            
            # === START TRACKING NEW MARKET ===
            if ticker not in self.tracked_markets:
                # Get floor_strike ONCE at open (Kalshi API call)
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
            
            # === PROCESS COIN PRICE CROSS DETECTION ===
            tracking = self.tracked_markets[ticker]
            if not tracking.coin_crossed:
                self._detect_coin_cross(tracking, coin_price)
    
    def _poll_yes_prices(self):
        """
        Poll Kalshi for YES prices - ONLY for markets not yet YES-crossed.
        Stop polling after cross detected + 2 confirmations.
        """
        # Get current coin prices for correlation
        coin_prices = get_all_coinbase_prices()
        
        for ticker, tracking in list(self.tracked_markets.items()):
            if tracking.finalized:
                continue
            
            # Only poll if we should (not yet crossed, or confirming)
            if not tracking.should_poll_yes():
                continue
            
            yes_price = self._get_yes_price(ticker)
            if yes_price is None:
                continue
            
            # Get coin price for this market
            coin_price = coin_prices.get(tracking.coin)
            
            # Detect YES cross
            self._detect_yes_cross(tracking, yes_price, coin_price or 0)
    
    def _check_settlements(self):
        """Check if any tracked markets have settled."""
        for ticker, tracking in list(self.tracked_markets.items()):
            if tracking.finalized:
                continue
            
            result = self._get_market_result(ticker)
            if result is not None:
                self._finalize_market(tracking, result)
    
    def _finalize_market(self, tracking: MarketTracking, result: str):
        """Finalize tracking data when market closes - ONE Kalshi call at expiry."""
        tracking.finalized = True
        tracking.yes_won = (result == 'yes')
        
        # Get final coin price (Coinbase - no rate limit)
        final_price = get_coinbase_price(tracking.coin)
        if final_price:
            tracking.final_coin_price = final_price
        
        # Get final YES price (ONE Kalshi call at expiry)
        final_yes = self._get_yes_price(tracking.ticker)
        if final_yes is not None:
            tracking.final_yes_price = final_yes
        
        # Analyze YES $0.50 cross prediction
        if tracking.yes_first_cross is not None:
            if tracking.yes_first_cross == "up":
                tracking.analysis["yes_cross_correct"] = tracking.yes_won == True
            else:
                tracking.analysis["yes_cross_correct"] = tracking.yes_won == False
        else:
            tracking.analysis["yes_cross_correct"] = None
        
        # Analyze coin target cross prediction
        if tracking.coin_first_cross is not None:
            if tracking.coin_first_cross == "up":
                tracking.analysis["coin_cross_correct"] = tracking.yes_won == True
            else:
                tracking.analysis["coin_cross_correct"] = tracking.yes_won == False
        else:
            tracking.analysis["coin_cross_correct"] = None
        
        # Save to file
        self._save_record(tracking)
        
        logger.info(
            f"🏁 FINALIZED {tracking.ticker} | "
            f"YES cross: {tracking.yes_first_cross or 'N/A'} @ {tracking.yes_cross_time or 'N/A'} | "
            f"Coin cross: {tracking.coin_first_cross or 'N/A'} @ {tracking.coin_cross_time or 'N/A'} | "
            f"YES {'WON' if tracking.yes_won else 'LOST'} | "
            f"YES cross correct: {tracking.analysis.get('yes_cross_correct')} | "
            f"Coin cross correct: {tracking.analysis.get('coin_cross_correct')}"
        )
        
        # Remove from active tracking
        del self.tracked_markets[tracking.ticker]
    
    def _save_record(self, tracking: MarketTracking):
        """Save tracking record to JSON file."""
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "coin": tracking.coin,
            "market": tracking.market_time,
            "target_price": tracking.target_price,
            
            # Coinbase-based coin crossing
            "coin_first_cross": tracking.coin_first_cross,
            "coin_cross_price": tracking.coin_cross_price,
            "coin_cross_time": tracking.coin_cross_time,
            
            # Kalshi YES crossing
            "yes_first_cross": tracking.yes_first_cross,
            "yes_cross_price": tracking.yes_cross_price,
            "yes_cross_time": tracking.yes_cross_time,
            "coin_price_at_yes_cross": tracking.coin_price_at_yes_cross,
            
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
                f"through $0.50 at {tracking.yes_cross_time or 'N/A'}; "
                f"{tracking.coin} crossed {'UP' if tracking.coin_first_cross == 'up' else 'DOWN' if tracking.coin_first_cross == 'down' else 'NEITHER'} "
                f"through target ${tracking.target_price:,.2f} at {tracking.coin_cross_time or 'N/A'}"
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
        
        # Check for duplicate by coin + market_time
        existing_idx = None
        record_key = f"{tracking.coin}_{tracking.market_time}"
        for i, r in enumerate(records):
            r_key = f"{r.get('coin', '')}_{r.get('market', '')}"
            if r_key == record_key:
                existing_idx = i
                break
        
        if existing_idx is not None:
            records[existing_idx] = record
        else:
            records.append(record)
        
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
        
        stats = {}
        for coin in COINS:
            coin_records = [
                r for r in records 
                if r.get('coin') == coin and r.get('analysis', {}).get('coin_cross_correct') is not None
            ]
            if not coin_records:
                continue
            
            total = len(coin_records)
            coin_correct = sum(1 for r in coin_records if r.get('analysis', {}).get('coin_cross_correct'))
            
            # YES cross stats
            yes_cross_records = [r for r in coin_records if r.get('yes_first_cross') is not None]
            yes_cross_correct = sum(1 for r in yes_cross_records if r.get('analysis', {}).get('yes_cross_correct'))
            
            # Coin cross breakdown
            cross_up_records = [r for r in coin_records if r.get('coin_first_cross') == 'up']
            cross_down_records = [r for r in coin_records if r.get('coin_first_cross') == 'down']
            cross_up_correct = sum(1 for r in cross_up_records if r.get('analysis', {}).get('coin_cross_correct'))
            cross_down_correct = sum(1 for r in cross_down_records if r.get('analysis', {}).get('coin_cross_correct'))
            
            # YES cross breakdown
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
        
        logger.info("=" * 70)
        logger.info("🎯 TARGET CROSS ACCURACY STATS (v2 - Rate-Limit Friendly)")
        logger.info("Architecture:")
        logger.info("  1. Kalshi ONCE at open → target price")
        logger.info("  2. Coinbase every 5s → real-time coin tracking")
        logger.info("  3. Kalshi every 30s → YES price (stop after cross + 2 confirmations)")
        logger.info("  4. Kalshi ONCE at expiry → final resolution")
        logger.info("=" * 70)
        
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
        
        logger.info("=" * 70)
    
    def run(self):
        """Main tracking loop."""
        logger.info("🚀 Target Cross Tracker v2 starting main loop...")
        
        try:
            while True:
                try:
                    self.poll_markets()
                    
                    # Print stats every 120 polls (~10 minutes with 5s Coinbase interval)
                    if self.poll_count % 120 == 0 and self.poll_count > 0:
                        self.print_stats()
                    
                    # Sleep 1 second between poll cycles (coordination loop)
                    time.sleep(1)
                    
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
