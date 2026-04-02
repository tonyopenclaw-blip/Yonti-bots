#!/usr/bin/env python3
"""
Kalshi Market Scanner - Searcher Bot
Finds active 15-minute crypto markets on Kalshi
"""

import requests
import json
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional

# Kalshi API Config
KALSHI_ACCESS_KEY = os.environ.get("KALSHI_ACCESS_KEY", "0ebe781e-ce07-4e19-98eb-0d2d8e0ea20b")
KALSHI_API_BASE = "https://api.elections.kalshi.com/trade-api/v2"

# Market series we scan
SERIES = {
    "BTC": "KXBTC15M",
    "ETH": "KXETH15M",
    "SOL": "KXSOL15M",
    "XRP": "KXXRP15M",
    "DOGE": "KXDOGE15M",
    "BNB": "KXBNB15M",
    "HYPE": "KXHYPE15M",
}

HEADERS = {
    "KALSHI-ACCESS-KEY": KALSHI_ACCESS_KEY,
    "Content-Type": "application/json"
}


def generate_ticker_suffix(dt: datetime = None) -> str:
    """
    Generate ticker suffix for 15-min market.
    Format: YYMMDDHHMM-NN where NN is the interval offset (00, 15, 30, or 45)
    Example: 26APR011930-30 (for the :30 interval)
    """
    if dt is None:
        dt = datetime.utcnow()
    
    # Round down to nearest 15-min interval
    minute = (dt.minute // 15) * 15
    dt_rounded = dt.replace(minute=minute, second=0, microsecond=0)
    
    month_abbr = dt_rounded.strftime("%b").upper()
    # Determine interval offset: 00->00, 15->15, 30->30, 45->45
    interval_offset = f"{minute:02d}"
    suffix = dt_rounded.strftime(f"%y{month_abbr}%d%H%M-{interval_offset}")
    
    return suffix


def get_current_15min_window() -> tuple:
    """
    Get the current 15-min window start time.
    """
    now = datetime.utcnow()
    minute = (now.minute // 15) * 15
    window_start = now.replace(minute=minute, second=0, microsecond=0)
    window_end = window_start + timedelta(minutes=15)
    
    return window_start, window_end


def generate_tickers_for_window(window_start: datetime = None) -> List[str]:
    """Generate ticker suffixes for scanning."""
    if window_start is None:
        window_start, _ = get_current_15min_window()
    
    tickers = []
    for i in range(4):
        window = window_start + timedelta(minutes=i * 15)
        suffix = generate_ticker_suffix(window)
        tickers.append(suffix)
    
    return tickers


def check_market(series_ticker: str, suffix: str) -> Optional[Dict]:
    """Check if a specific market exists and get its status."""
    ticker = f"{series_ticker}-{suffix}"
    url = f"{KALSHI_API_BASE}/markets/{ticker}"
    
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        if response.status_code == 200:
            data = response.json()
            return {
                "ticker": ticker,
                "status": data.get("status", "unknown"),
                "yes_bid": data.get("yes_bid", 0),
                "yes_ask": data.get("yes_ask", 0),
                "close_time": data.get("close_time", ""),
                "resolution_time": data.get("resolution_time", ""),
            }
        return None
    except Exception as e:
        return None


def list_markets_in_series(series_ticker: str, limit: int = 20) -> List[Dict]:
    """
    List markets in a series (e.g., KXBTC15M).
    Returns ALL markets - filter for tradeable ones below.
    """
    url = f"{KALSHI_API_BASE}/markets"
    params = {
        "series_ticker": series_ticker,
        "status": "open",
        "limit": limit
    }
    
    try:
        response = requests.get(url, headers=HEADERS, params=params, timeout=15)
        if response.status_code == 200:
            data = response.json()
            markets = data.get("markets", [])
            
            result = []
            for m in markets:
                result.append({
                    "ticker": m.get("ticker", ""),
                    "status": m.get("status", ""),
                    "yes_bid": float(m.get("yes_bid_dollars", 0)),
                    "yes_ask": float(m.get("yes_ask_dollars", 0)),
                    "close_time": m.get("close_time", ""),
                    "resolution_time": m.get("resolution_time", ""),
                })
            return result
        return []
    except Exception as e:
        print(f"Error listing markets for {series_ticker}: {e}")
        return []


def is_market_tradeable(market: Dict) -> bool:
    """
    Check if a market is tradeable.
    Criteria:
    - Has a real price (yes_ask > 0)
    - Status is NOT finalized
    - Market has opened (close_time in future)
    """
    # Must have a price
    if market.get("yes_ask", 0) <= 0:
        return False
    
    # Must not be finalized
    if market.get("status") == "finalized":
        return False
    
    # Check if market has opened (close_time must be in the future)
    close_time_str = market.get("close_time", "")
    if close_time_str:
        try:
            # Parse close_time and compare with current UTC
            close_time = datetime.fromisoformat(close_time_str.replace("Z", ""))
            now = datetime.utcnow()
            if close_time.tzinfo:
                close_time = close_time.replace(tzinfo=None)
            if close_time < now:
                return False
        except:
            pass
    
    return True


def scan_all_series() -> Dict[str, List[Dict]]:
    """
    Scan all configured series for ACTIVE (tradeable) markets.
    Returns dict of series -> tradeable markets.
    """
    results = {}
    
    for coin, series in SERIES.items():
        markets = list_markets_in_series(series, limit=30)
        
        # Filter for tradeable markets
        tradeable = [m for m in markets if is_market_tradeable(m)]
        
        if tradeable:
            results[coin] = tradeable
    
    return results


def format_market_summary(markets_by_series: Dict[str, List[Dict]]) -> str:
    """Format scan results for display/logging."""
    if not markets_by_series:
        return "No tradeable markets found."
    
    lines = []
    lines.append(f"SCAN RESULTS - {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("=" * 60)
    
    total = 0
    for coin, markets in markets_by_series.items():
        lines.append(f"\n{coin} ({SERIES[coin]}):")
        for m in markets:
            ticker = m.get("ticker", "")
            status = m.get("status", "")
            yes_ask = m.get("yes_ask", 0)
            
            price_str = f"${yes_ask:.2f}" if yes_ask else "N/A"
            lines.append(f"  {ticker} | {status} | YES: {price_str}")
            total += 1
    
    lines.append(f"\n{'=' * 60}")
    lines.append(f"Total tradeable markets: {total}")
    
    return "\n".join(lines)


def save_live_markets(markets_by_series: Dict[str, List[Dict]], filepath: str):
    """Save live markets to JSON file for other bots to use."""
    output = {
        "updated_at": datetime.utcnow().isoformat(),
        "market_count": sum(len(m) for m in markets_by_series.values()),
        "markets": markets_by_series
    }
    
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w") as f:
        json.dump(output, f, indent=2)


def main():
    """Main scanner loop."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_file = os.path.join(script_dir, "..", "data", "live_markets.json")
    
    print("Kalshi Market Scanner starting...")
    
    window_start, window_end = get_current_15min_window()
    tickers = generate_tickers_for_window(window_start)
    
    print(f"Current 15-min window: {window_start.strftime('%H:%M')} - {window_end.strftime('%H:%M')} UTC")
    print(f"Checking tickers: {tickers}")
    
    print("\nScanning all series...")
    results = scan_all_series()
    
    summary = format_market_summary(results)
    print(f"\n{summary}")
    
    save_live_markets(results, output_file)
    print(f"\nSaved to {output_file}")
    
    return results


if __name__ == "__main__":
    main()
