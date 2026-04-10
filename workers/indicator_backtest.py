#!/usr/bin/env python3
"""
Technical Indicator Backtest for Kalshi 15-min Crypto Binaries
Analyzes: RSI, MACD, OBV, Moving Averages, Volume Spikes
"""

import json
import requests
from datetime import datetime, timezone
from typing import Dict, List
import statistics

COINBASE_API = "https://api.exchange.coinbase.com"
PRODUCTS = {
    "BTC": "BTC-USD", "ETH": "ETH-USD", "SOL": "SOL-USD",
    "BNB": "BNB-USD", "DOGE": "DOGE-USD", "XRP": "XRP-USD",
    "HYPE": "HYPE-USD", "ADA": "ADA-USD"
}
GRANULARITY = 900  # 15 minutes

def fetch_candles(product_id: str, hours: int = 300) -> List[Dict]:
    """Fetch 15-min candles from Coinbase"""
    url = f"{COINBASE_API}/products/{product_id}/candles"
    now_ts = int(datetime.now(timezone.utc).timestamp())
    params = {"granularity": GRANULARITY, "time": now_ts}
    
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        
        candles = []
        for c in data:
            candles.append({
                "time": c[0], "low": c[1], "high": c[2],
                "open": c[3], "close": c[4], "volume": c[5]
            })
        # API returns newest first, reverse for chronological
        candles.reverse()
        return candles
    except Exception as e:
        print(f"Error fetching {product_id}: {e}")
        return []

def calc_rsi(prices: List[float], period: int = 14) -> List[float]:
    """Calculate RSI"""
    if len(prices) < period + 1:
        return [50.0] * len(prices)
    
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains = [d if d > 0 else 0 for d in deltas[-period:]]
    losses = [-d if d < 0 else 0 for d in deltas[-period:]]
    
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    
    rsi_values = [50.0] * (period + 1)
    
    for i in range(period, len(prices)):
        if i > period:
            avg_gain = (avg_gain * (period - 1) + gains[-1]) / period
            avg_loss = (avg_loss * (period - 1) + losses[-1]) / period
        
        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
        rsi_values.append(rsi)
    
    # Pad to full length
    while len(rsi_values) < len(prices):
        rsi_values.insert(0, 50.0)
    
    return rsi_values

def calc_macd(prices: List[float], fast: int = 12, slow: int = 26, signal: int = 9):
    """Calculate MACD - returns (macd_line, signal_line, histogram)"""
    if len(prices) < slow + signal:
        return [0] * len(prices), [0] * len(prices), [0] * len(prices)
    
    # EMA calculation
    def ema(data, period):
        k = 2 / (period + 1)
        ema_vals = [data[0]]
        for d in data[1:]:
            ema_vals.append(d * k + ema_vals[-1] * (1 - k))
        return ema_vals
    
    ema_fast = ema(prices, fast)
    ema_slow = ema(prices, slow)
    
    macd_line = [ema_fast[i] - ema_slow[i] for i in range(len(prices))]
    signal_line = ema(macd_line, signal)
    histogram = [macd_line[i] - signal_line[i] if i < len(signal_line) else 0 for i in range(len(macd_line))]
    
    return macd_line, signal_line, histogram

def calc_obv(prices: List[float], volumes: List[float]) -> List[float]:
    """Calculate OBV"""
    obv = [0]
    for i in range(1, len(prices)):
        if prices[i] > prices[i-1]:
            obv.append(obv[-1] + volumes[i])
        elif prices[i] < prices[i-1]:
            obv.append(obv[-1] - volumes[i])
        else:
            obv.append(obv[-1])
    return obv

def calc_ma(prices: List[float], period: int) -> List[float]:
    """Calculate Simple Moving Average"""
    ma = []
    for i in range(len(prices)):
        if i < period - 1:
            ma.append(prices[i])
        else:
            ma.append(sum(prices[i-period+1:i+1]) / period)
    return ma

def analyze_coin(coin: str, candles: List[Dict]) -> Dict:
    """Analyze all indicators for a coin"""
    if len(candles) < 60:
        return {"coin": coin, "error": "Insufficient data"}
    
    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    volumes = [c["volume"] for c in candles]
    
    # Calculate indicators
    rsi = calc_rsi(closes, 14)
    macd_line, signal_line, histogram = calc_macd(closes)
    obv = calc_obv(closes, volumes)
    ma50 = calc_ma(closes, 50)
    ma20 = calc_ma(closes, 20)
    
    # Volume metrics
    avg_volume = statistics.mean(volumes[-60:])
    volume_spike_threshold = avg_volume * 1.5
    
    results = {
        "coin": coin,
        "total_candles": len(candles),
        "rsi_oversold_hits": 0, "rsi_oversold_up": 0,
        "rsi_overbought_hits": 0, "rsi_overbought_down": 0,
        "macd_bullish_cross_hits": 0, "macd_bullish_up": 0,
        "macd_bearish_cross_hits": 0, "macd_bearish_down": 0,
        "price_below_ma50_hits": 0, "price_below_ma50_up": 0,
        "price_above_ma50_hits": 0, "price_above_ma50_cont": 0,
        "volume_spike_hits": 0, "volume_spike_reversal": 0,
        "triple_bullish_hits": 0, "triple_bullish_up": 0,
        "obv_divergence_hits": 0, "obv_divergence_up": 0,
    }
    
    # Backtest: iterate through candles (need index 60+ for all indicators)
    for i in range(60, len(candles) - 1):
        # Current state
        curr_rsi = rsi[i]
        prev_rsi = rsi[i-1]
        curr_macd = macd_line[i]
        prev_macd = macd_line[i-1]
        curr_signal = signal_line[i]
        prev_signal = signal_line[i-1]
        curr_hist = histogram[i]
        prev_hist = histogram[i-1]
        curr_price = closes[i]
        next_price = closes[i+1]
        price_change = (next_price - curr_price) / curr_price
        curr_ma50 = ma50[i]
        curr_ma20 = ma20[i]
        curr_obv = obv[i]
        prev_obv = obv[i-1]
        curr_vol = volumes[i]
        
        price_went_up = price_change > 0.001  # >0.1% up
        price_went_down = price_change < -0.001  # >0.1% down
        
        # 1. RSI Oversold (RSI < 30) - does it bounce?
        if curr_rsi < 30:
            results["rsi_oversold_hits"] += 1
            if price_went_up:
                results["rsi_oversold_up"] += 1
        
        # 2. RSI Overbought (RSI > 70) - does it drop?
        if curr_rsi > 70:
            results["rsi_overbought_hits"] += 1
            if price_went_down:
                results["rsi_overbought_down"] += 1
        
        # 3. MACD Bullish Cross (MACD crosses above signal)
        if prev_macd <= prev_signal and curr_macd > curr_signal:
            results["macd_bullish_cross_hits"] += 1
            if price_went_up:
                results["macd_bullish_up"] += 1
        
        # 4. MACD Bearish Cross (MACD crosses below signal)
        if prev_macd >= prev_signal and curr_macd < curr_signal:
            results["macd_bearish_cross_hits"] += 1
            if price_went_down:
                results["macd_bearish_down"] += 1
        
        # 5. Price below MA50 - mean reversion?
        if curr_price < curr_ma50:
            results["price_below_ma50_hits"] += 1
            if price_went_up:
                results["price_below_ma50_up"] += 1
        
        # 6. Price above MA50 - trend continuation?
        if curr_price > curr_ma50:
            results["price_above_ma50_hits"] += 1
            if price_went_up:
                results["price_above_ma50_cont"] += 1
        
        # 7. Volume spike + reversal check
        if curr_vol > volume_spike_threshold:
            results["volume_spike_hits"] += 1
            # Check if price reversed within next 2 candles
            if i + 2 < len(closes):
                future_change = (closes[i+2] - closes[i]) / closes[i]
                # Reversal = price went opposite direction of spike
                if curr_price > curr_ma50 and future_change < -0.002:  # was above, dropped
                    results["volume_spike_reversal"] += 1
                elif curr_price < curr_ma50 and future_change > 0.002:  # was below, rose
                    results["volume_spike_reversal"] += 1
        
        # 8. Triple bullish (RSI < 40 + MACD bullish cross + price below MA50)
        if curr_rsi < 40 and prev_macd <= prev_signal and curr_macd > curr_signal and curr_price < curr_ma50:
            results["triple_bullish_hits"] += 1
            if price_went_up:
                results["triple_bullish_up"] += 1
        
        # 9. OBV divergence (price making new low but OBV higher = bullish)
        if i > 100:
            recent_low_idx = lows.index(min(lows[max(0,i-20):i+1])) if i >= 20 else i
            if recent_low_idx < i - 5:  # Recent low was at least 5 candles ago
                price_made_new_low = lows[i] < min(lows[max(0,i-20):i])
                obv_higher = obv[i] > statistics.mean(obv[max(0,i-20):i])
                if price_made_new_low and obv_higher:
                    results["obv_divergence_hits"] += 1
                    if price_went_up:
                        results["obv_divergence_up"] += 1
    
    return results

def calc_win_rates(results: Dict) -> Dict:
    """Calculate win rates from raw counts"""
    win_rates = {}
    
    # RSI Oversold Bounce
    if results["rsi_oversold_hits"] > 0:
        win_rates["rsi_oversold_bounce"] = {
            "hits": results["rsi_oversold_hits"],
            "win_rate": results["rsi_oversold_up"] / results["rsi_oversold_hits"] * 100,
            "bounce_prob": results["rsi_oversold_up"] / results["rsi_oversold_hits"]
        }
    
    # RSI Overbought Drop
    if results["rsi_overbought_hits"] > 0:
        win_rates["rsi_overbought_drop"] = {
            "hits": results["rsi_overbought_hits"],
            "win_rate": results["rsi_overbought_down"] / results["rsi_overbought_hits"] * 100
        }
    
    # MACD Bullish Cross
    if results["macd_bullish_cross_hits"] > 0:
        win_rates["macd_bullish_cross"] = {
            "hits": results["macd_bullish_cross_hits"],
            "win_rate": results["macd_bullish_up"] / results["macd_bullish_cross_hits"] * 100
        }
    
    # MACD Bearish Cross
    if results["macd_bearish_cross_hits"] > 0:
        win_rates["macd_bearish_cross"] = {
            "hits": results["macd_bearish_cross_hits"],
            "win_rate": results["macd_bearish_down"] / results["macd_bearish_cross_hits"] * 100
        }
    
    # Price below MA50 bounce
    if results["price_below_ma50_hits"] > 0:
        win_rates["below_ma50_bounce"] = {
            "hits": results["price_below_ma50_hits"],
            "win_rate": results["price_below_ma50_up"] / results["price_below_ma50_hits"] * 100
        }
    
    # Price above MA50 continuation
    if results["price_above_ma50_hits"] > 0:
        win_rates["above_ma50_continuation"] = {
            "hits": results["price_above_ma50_hits"],
            "win_rate": results["price_above_ma50_cont"] / results["price_above_ma50_hits"] * 100
        }
    
    # Triple Bullish
    if results["triple_bullish_hits"] > 0:
        win_rates["triple_bullish"] = {
            "hits": results["triple_bullish_hits"],
            "win_rate": results["triple_bullish_up"] / results["triple_bullish_hits"] * 100
        }
    
    # Volume Spike Reversal
    if results["volume_spike_hits"] > 0:
        win_rates["volume_spike_reversal"] = {
            "hits": results["volume_spike_hits"],
            "win_rate": results["volume_spike_reversal"] / results["volume_spike_hits"] * 100
        }
    
    # OBV Divergence
    if results["obv_divergence_hits"] > 0:
        win_rates["obv_bullish_divergence"] = {
            "hits": results["obv_divergence_hits"],
            "win_rate": results["obv_divergence_up"] / results["obv_divergence_hits"] * 100
        }
    
    return win_rates

def main():
    print("=" * 70)
    print("📊 TECHNICAL INDICATOR BACKTEST - 15-MIN CRYPTO")
    print("=" * 70)
    print("\nFetching data from Coinbase...\n")
    
    all_results = {}
    aggregated = {
        "rsi_oversold_hits": 0, "rsi_oversold_up": 0,
        "rsi_overbought_hits": 0, "rsi_overbought_down": 0,
        "macd_bullish_cross_hits": 0, "macd_bullish_up": 0,
        "macd_bearish_cross_hits": 0, "macd_bearish_down": 0,
        "price_below_ma50_hits": 0, "price_below_ma50_up": 0,
        "price_above_ma50_hits": 0, "price_above_ma50_cont": 0,
        "volume_spike_hits": 0, "volume_spike_reversal": 0,
        "triple_bullish_hits": 0, "triple_bullish_up": 0,
        "obv_divergence_hits": 0, "obv_divergence_up": 0,
    }
    
    for coin, product_id in PRODUCTS.items():
        print(f"  Fetching {coin}...")
        candles = fetch_candles(product_id, hours=300)
        if len(candles) > 60:
            results = analyze_coin(coin, candles)
            all_results[coin] = results
            print(f"    -> {len(candles)} candles, {results['total_candles']} analyzed")
            
            # Aggregate
            for key in aggregated:
                if key in results:
                    aggregated[key] += results[key]
        else:
            print(f"    -> Insufficient data ({len(candles)} candles)")
    
    # Calculate aggregated win rates
    agg_win_rates = calc_win_rates(aggregated)
    
    # Print results
    print("\n" + "=" * 70)
    print("📈 AGGREGATED WIN RATES (All Coins Combined)")
    print("=" * 70)
    
    print("\n🎯 RSI INDICATORS (15-min timeframe only)")
    print("-" * 50)
    
    if "rsi_oversold_bounce" in agg_win_rates:
        r = agg_win_rates["rsi_oversold_bounce"]
        print(f"  RSI < 30 (Oversold) → Price goes UP:      {r['win_rate']:.1f}% ({r['hits']} occurrences)")
        print(f"    -> Edge over random: +{(r['win_rate']-50):.1f}%")
    
    if "rsi_overbought_drop" in agg_win_rates:
        r = agg_win_rates["rsi_overbought_drop"]
        print(f"  RSI > 70 (Overbought) → Price goes DOWN: {r['win_rate']:.1f}% ({r['hits']} occurrences)")
        print(f"    -> Edge over random: +{(r['win_rate']-50):.1f}%")
    
    print("\n🎯 MACD INDICATORS (15-min timeframe)")
    print("-" * 50)
    
    if "macd_bullish_cross" in agg_win_rates:
        r = agg_win_rates["macd_bullish_cross"]
        print(f"  MACD Bullish Cross → Price goes UP:      {r['win_rate']:.1f}% ({r['hits']} occurrences)")
        print(f"    -> Edge over random: +{(r['win_rate']-50):.1f}%")
    
    if "macd_bearish_cross" in agg_win_rates:
        r = agg_win_rates["macd_bearish_cross"]
        print(f"  MACD Bearish Cross → Price goes DOWN:    {r['win_rate']:.1f}% ({r['hits']} occurrences)")
        print(f"    -> Edge over random: +{(r['win_rate']-50):.1f}%")
    
    print("\n🎯 MOVING AVERAGE INDICATORS (15-min timeframe)")
    print("-" * 50)
    
    if "below_ma50_bounce" in agg_win_rates:
        r = agg_win_rates["below_ma50_bounce"]
        print(f"  Price < MA50 → Mean Reversion UP:        {r['win_rate']:.1f}% ({r['hits']} occurrences)")
        print(f"    -> Edge over random: +{(r['win_rate']-50):.1f}%")
    
    if "above_ma50_continuation" in agg_win_rates:
        r = agg_win_rates["above_ma50_continuation"]
        print(f"  Price > MA50 → Trend Continuation UP:     {r['win_rate']:.1f}% ({r['hits']} occurrences)")
        print(f"    -> Edge over random: +{(r['win_rate']-50):.1f}%")
    
    print("\n🎯 VOLUME & OBV INDICATORS (15-min timeframe)")
    print("-" * 50)
    
    if "volume_spike_reversal" in agg_win_rates:
        r = agg_win_rates["volume_spike_reversal"]
        print(f"  Volume Spike (>1.5x avg) → Reversal:      {r['win_rate']:.1f}% ({r['hits']} occurrences)")
    
    if "obv_bullish_divergence" in agg_win_rates:
        r = agg_win_rates["obv_bullish_divergence"]
        print(f"  OBV Bullish Divergence → Price UP:        {r['win_rate']:.1f}% ({r['hits']} occurrences)")
        print(f"    -> Edge over random: +{(r['win_rate']-50):.1f}%")
    
    print("\n🎯 COMBO INDICATORS (15-min timeframe)")
    print("-" * 50)
    
    if "triple_bullish" in agg_win_rates:
        r = agg_win_rates["triple_bullish"]
        print(f"  RSI < 40 + MACD Bullish + Below MA50:     {r['win_rate']:.1f}% ({r['hits']} occurrences)")
        print(f"    -> Edge over random: +{(r['win_rate']-50):.1f}%")
    
    # Summary
    print("\n" + "=" * 70)
    print("📋 KEY FINDINGS SUMMARY")
    print("=" * 70)
    
    # Find best edge
    best_edges = []
    for name, data in agg_win_rates.items():
        if data['hits'] >= 20:  # Only consider if we have decent sample
            edge = data['win_rate'] - 50
            best_edges.append((name, data['win_rate'], data['hits'], edge))
    
    best_edges.sort(key=lambda x: x[3], reverse=True)
    
    print("\n🏆 TOP INDICATORS BY EDGE (sample size >= 20):")
    for name, win_rate, hits, edge in best_edges[:5]:
        direction = "📈" if edge > 0 else "📉"
        print(f"  {direction} {name}: {win_rate:.1f}% win rate ({hits} hits), edge={edge:+.1f}%")
    
    print("\n⚠️  DATA LIMITATIONS:")
    print("  - Coinbase API only provides 15-min candles (no 5m or 30m data)")
    print("  - Results below are timeframe-specific to 15-min only")
    print("  - Sample includes ~300 candles per coin (approx 3 days of data)")
    
    # Save to file
    output = {
        "analysis_date": datetime.now(timezone.utc).isoformat(),
        "timeframes_available": ["15-min only (Coinbase limitation)"],
        "coins_analyzed": list(all_results.keys()),
        "aggregated_win_rates": agg_win_rates,
        "best_edges": [{"indicator": x[0], "win_rate": x[1], "hits": x[2], "edge": x[3]} for x in best_edges],
        "per_coin_results": all_results
    }
    
    with open("/home/ubuntu/.openclaw/workspace/memory/nerd-indicator-analysis.md", "w") as f:
        f.write("# Technical Indicator Analysis for Kalshi 15-min Crypto Binaries\n\n")
        f.write(f"**Analysis Date:** {datetime.now(timezone.utc).isoformat()}\n\n")
        f.write("## ⚠️ Important Data Limitation\n\n")
        f.write("Coinbase Exchange API only provides **15-minute candles** (granularity=900).\n")
        f.write("- **5-minute data:** NOT AVAILABLE from Coinbase\n")
        f.write("- **30-minute data:** NOT AVAILABLE from Coinbase (would need to aggregate 15m)\n")
        f.write("- **Results below are specific to 15-minute timeframe only**\n\n")
        f.write("## Coins Analyzed\n\n")
        f.write(", ".join(all_results.keys()) + "\n\n")
        f.write("---\n\n")
        f.write("## 📊 AGGREGATED WIN RATES (All 8 Coins Combined)\n\n")
        f.write("### RSI Indicators (15-min)\n\n")
        if "rsi_oversold_bounce" in agg_win_rates:
            r = agg_win_rates["rsi_oversold_bounce"]
            f.write(f"- **RSI < 30 (Oversold) → Price goes UP:** {r['win_rate']:.1f}% win rate ({r['hits']} occurrences)\n")
            f.write(f"  - Edge over random: +{r['win_rate']-50:.1f}%\n\n")
        if "rsi_overbought_drop" in agg_win_rates:
            r = agg_win_rates["rsi_overbought_drop"]
            f.write(f"- **RSI > 70 (Overbought) → Price goes DOWN:** {r['win_rate']:.1f}% win rate ({r['hits']} occurrences)\n")
            f.write(f"  - Edge over random: +{r['win_rate']-50:.1f}%\n\n")
        f.write("### MACD Indicators (15-min)\n\n")
        if "macd_bullish_cross" in agg_win_rates:
            r = agg_win_rates["macd_bullish_cross"]
            f.write(f"- **MACD Bullish Cross → Price goes UP:** {r['win_rate']:.1f}% win rate ({r['hits']} occurrences)\n")
            f.write(f"  - Edge over random: +{r['win_rate']-50:.1f}%\n\n")
        if "macd_bearish_cross" in agg_win_rates:
            r = agg_win_rates["macd_bearish_cross"]
            f.write(f"- **MACD Bearish Cross → Price goes DOWN:** {r['win_rate']:.1f}% win rate ({r['hits']} occurrences)\n")
            f.write(f"  - Edge over random: +{r['win_rate']-50:.1f}%\n\n")
        f.write("### Moving Average Indicators (15-min)\n\n")
        if "below_ma50_bounce" in agg_win_rates:
            r = agg_win_rates["below_ma50_bounce"]
            f.write(f"- **Price < MA50 → Mean Reversion UP:** {r['win_rate']:.1f}% win rate ({r['hits']} occurrences)\n")
            f.write(f"  - Edge over random: +{r['win_rate']-50:.1f}%\n\n")
        if "above_ma50_continuation" in agg_win_rates:
            r = agg_win_rates["above_ma50_continuation"]
            f.write(f"- **Price > MA50 → Trend Continuation UP:** {r['win_rate']:.1f}% win rate ({r['hits']} occurrences)\n")
            f.write(f"  - Edge over random: +{r['win_rate']-50:.1f}%\n\n")
        f.write("### Volume & OBV Indicators (15-min)\n\n")
        if "volume_spike_reversal" in agg_win_rates:
            r = agg_win_rates["volume_spike_reversal"]
            f.write(f"- **Volume Spike (>1.5x avg) → Reversal:** {r['win_rate']:.1f}% win rate ({r['hits']} occurrences)\n\n")
        if "obv_bullish_divergence" in agg_win_rates:
            r = agg_win_rates["obv_bullish_divergence"]
            f.write(f"- **OBV Bullish Divergence → Price UP:** {r['win_rate']:.1f}% win rate ({r['hits']} occurrences)\n")
            f.write(f"  - Edge over random: +{r['win_rate']-50:.1f}%\n\n")
        f.write("### Combo Indicators (15-min)\n\n")
        if "triple_bullish" in agg_win_rates:
            r = agg_win_rates["triple_bullish"]
            f.write(f"- **RSI < 40 + MACD Bullish + Below MA50 → Price UP:** {r['win_rate']:.1f}% win rate ({r['hits']} occurrences)\n")
            f.write(f"  - Edge over random: +{r['win_rate']-50:.1f}%\n\n")
        f.write("---\n\n")
        f.write("## 🏆 TOP INDICATORS BY EDGE (sample >= 20)\n\n")
        for name, win_rate, hits, edge in best_edges[:5]:
            direction = "BULLISH" if edge > 0 else "BEARISH"
            f.write(f"{hits} hits) {name}: {win_rate:.1f}% win rate, edge={edge:+.1f}% ({direction})\n")
        f.write("\n## Specific Answers to Your Questions\n\n")
        if "rsi_oversold_bounce" in agg_win_rates:
            r = agg_win_rates["rsi_oversold_bounce"]
            f.write(f"**P(price goes UP | RSI < 30 at 15m):** {r['win_rate']:.1f}%\n\n")
        if "macd_bullish_cross" in agg_win_rates:
            r = agg_win_rates["macd_bullish_cross"]
            f.write(f"**P(price goes UP | MACD bullish cross at 15m):** {r['win_rate']:.1f}%\n\n")
        if "triple_bullish" in agg_win_rates:
            r = agg_win_rates["triple_bullish"]
            f.write(f"**P(price goes UP | RSI + MACD + OBV all bullish):** {r['win_rate']:.1f}%\n\n")
        f.write("---\n\n*Generated by Nerd subagent*\n")
    
    print(f"\n✅ Results saved to /home/ubuntu/.openclaw/workspace/memory/nerd-indicator-analysis.md")

if __name__ == "__main__":
    main()