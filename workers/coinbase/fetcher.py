#!/usr/bin/env python3
"""
📊 Coinbase 15-Minute Candle Fetcher

Fetches 15-min candles for BTC, ETH, SOL from Coinbase Exchange API.
No auth required for public market data.

Usage:
    python fetcher.py                    # Fetch latest candle for all coins
    python fetcher.py --coin BTC         # Fetch just BTC
    python fetcher.py --hours 4          # Fetch last 4 hours of candles
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import requests

# =============================================================================
# CONFIG
# =============================================================================
COINBASE_API = "https://api.exchange.coinbase.com"

# Coinbase product IDs for our coins
PRODUCTS = {
    "BTC": "BTC-USD",
    "ETH": "ETH-USD",
    "SOL": "SOL-USD",
}

GRANULARITY = 900  # 15 minutes in seconds

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / f"coinbase_{datetime.now(timezone.utc):%Y%m%d}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


# =============================================================================
# COINBASE API
# =============================================================================

def fetch_candles(product_id: str, hours: int = 1) -> List[Dict]:
    """
    Fetch 15-min candles for a product.
    
    Returns list of candles: [time, low, high, open, close, volume]
    Most recent candle is LAST in the list.
    """
    url = f"{COINBASE_API}/products/{product_id}/candles"
    params = {
        "granularity": GRANULARITY,
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        candles = []
        for candle in data:
            candles.append({
                "time": candle[0],
                "low": candle[1],
                "high": candle[2],
                "open": candle[3],
                "close": candle[4],
                "volume": candle[5],
                "dt": datetime.fromtimestamp(candle[0], tz=timezone.utc).isoformat(),
            })
        
        logger.info(f"Fetched {len(candles)} candles for {product_id}")
        return candles
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch {product_id}: {e}")
        return []


def get_latest_candle(product_id: str) -> Optional[Dict]:
    """Get the most recent completed 15-min candle."""
    candles = fetch_candles(product_id, hours=1)
    if candles:
        return candles[-1]  # Last = most recent
    return None


# =============================================================================
# CANDLE ANALYSIS
# =============================================================================

def analyze_candle(candle: Dict, coin: str = "BTC") -> Dict:
    """
    Analyze a single candle for patterns and indicators.
    Returns a dict with pattern signals and directional bias.
    """
    open_price = candle["open"]
    close_price = candle["close"]
    high_price = candle["high"]
    low_price = candle["low"]
    volume = candle["volume"]
    
    # Basic candle metrics
    body = abs(close_price - open_price)
    total_range = high_price - low_price if low_price > 0 else 1
    body_pct = body / total_range if total_range > 0 else 0
    upper_wick = high_price - max(open_price, close_price)
    lower_wick = min(open_price, close_price) - low_price
    
    # Direction
    is_bullish = close_price > open_price
    is_bearish = close_price < open_price
    
    # === PATTERN DETECTION ===
    patterns = []
    bias = "NEUTRAL"
    confidence = 0
    
    # Doji: tiny body (< 20% of range)
    if body_pct < 0.2 and (upper_wick > body * 2 or lower_wick > body * 2):
        patterns.append("DOJI")
        bias = "NEUTRAL"
        confidence = 30
    
    # Hammer: bullish, long lower wick (> 2x body), small upper wick
    elif is_bullish and lower_wick > body * 2 and upper_wick < body * 0.5:
        patterns.append("HAMMER")
        bias = "BULLISH"
        confidence = 65
    
    # Inverted Hammer / Shooting Star: bearish, long upper wick
    elif is_bearish and upper_wick > body * 2 and lower_wick < body * 0.5:
        patterns.append("SHOOTING_STAR")
        bias = "BEARISH"
        confidence = 65
    
    # Engulfing (need 2 candles - simplified here to single candle analysis)
    # Large body (> 70% of range) with small wicks = momentum candle
    elif body_pct > 0.7:
        if is_bullish:
            patterns.append("BULLISH_MOMENTUM")
            bias = "BULLISH"
            confidence = 55
        else:
            patterns.append("BEARISH_MOMENTUM")
            bias = "BEARISH"
            confidence = 55
    
    # Normal candle - default bias
    else:
        if is_bullish:
            bias = "BULLISH"
            confidence = 40
        else:
            bias = "BEARISH"
            confidence = 40
    
    # === FIBONACCI LEVEL (within candle's own range) ===
    fib_50 = (high_price + low_price) / 2
    near_50_fib = abs(close_price - fib_50) / total_range < 0.1 if total_range > 0 else False
    
    if near_50_fib:
        patterns.append("AT_50_FIB")
        confidence += 10  # Fibonacci at midpoint is significant
    
    # === VOLUME SIGNAL ===
    # Volume is relative - Coinbase returns raw volume, not normalized
    # For now, treat high volume as confirmation
    volume_signal = "NORMAL"
    # Would need historical average to properly assess
    
    return {
        "coin": coin,
        "timestamp": candle["dt"],
        "epoch": candle["time"],
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "close": close_price,
        "volume": volume,
        "change_pct": ((close_price - open_price) / open_price * 100) if open_price > 0 else 0,
        "body_pct": round(body_pct * 100, 1),
        "upper_wick_pct": round(upper_wick / total_range * 100, 1) if total_range > 0 else 0,
        "lower_wick_pct": round(lower_wick / total_range * 100, 1) if total_range > 0 else 0,
        "patterns": patterns,
        "bias": bias,
        "confidence": min(confidence, 95),
        "fib_50_level": fib_50,
        "near_50_fib": near_50_fib,
        "volume_signal": volume_signal,
    }


def multi_coin_analysis(coins: List[str] = None, hours: int = 1) -> List[Dict]:
    """
    Fetch and analyze candles for multiple coins.
    Returns list of analysis dicts.
    """
    if coins is None:
        coins = list(PRODUCTS.keys())
    
    results = []
    
    for coin in coins:
        product_id = PRODUCTS.get(coin.upper())
        if not product_id:
            logger.warning(f"Unknown coin: {coin}")
            continue
        
        candles = fetch_candles(product_id, hours=hours)
        if candles:
            # Analyze the latest (most recent) candle
            latest = candles[-1]
            analysis = analyze_candle(latest, coin=coin)
            
            # Also include previous candle for context
            if len(candles) >= 2:
                prev = candles[-2]
                analysis["prev_candle"] = {
                    "open": prev["open"],
                    "close": prev["close"],
                    "high": prev["high"],
                    "low": prev["low"],
                }
                # Detect engulfing
                prev_bullish = prev["close"] > prev["open"]
                curr_bullish = latest["close"] > latest["open"]
                if prev_bullish != curr_bullish and analysis["body_pct"] > 50:
                    if curr_bullish:
                        analysis["patterns"].append("BULLISH_ENGULFING")
                        analysis["bias"] = "BULLISH"
                        analysis["confidence"] = min(analysis["confidence"] + 20, 95)
                    else:
                        analysis["patterns"].append("BEARISH_ENGULFING")
                        analysis["bias"] = "BEARISH"
                        analysis["confidence"] = min(analysis["confidence"] + 20, 95)
            
            results.append(analysis)
    
    return results


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Coinbase 15-min Candle Fetcher")
    parser.add_argument(
        "--coin",
        choices=["BTC", "ETH", "SOL"],
        help="Specific coin to fetch (default: all)",
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=1,
        help="Hours of historical candles to fetch (default: 1)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON instead of human-readable",
    )
    args = parser.parse_args()
    
    coins = [args.coin] if args.coin else None
    results = multi_coin_analysis(coins=coins, hours=args.hours)
    
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print("\n" + "=" * 70)
        print("📊 COINBASE 15-MIN CANDLE ANALYSIS")
        print("=" * 70)
        
        for r in results:
            print(f"\n🪙 {r['coin']}-USD")
            print(f"   Time:    {r['timestamp']}")
            print(f"   O: ${r['open']:,.2f}  H: ${r['high']:,.2f}  L: ${r['low']:,.2f}  C: ${r['close']:,.2f}")
            print(f"   Change:  {r['change_pct']:+.2f}%")
            print(f"   Body:    {r['body_pct']:.0f}% of range | Wick: ↑{r['upper_wick_pct']:.0f}% ↓{r['lower_wick_pct']:.0f}%")
            print(f"   Patterns: {' | '.join(r['patterns']) if r['patterns'] else 'None'}")
            print(f"   Bias:    {r['bias']} (confidence: {r['confidence']}%)")
            if r.get('near_50_fib'):
                print(f"   🔶 At 50% Fibonacci retracement level (${r['fib_50_level']:,.2f})")
        
        print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
