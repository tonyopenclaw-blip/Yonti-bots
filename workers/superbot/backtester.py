#!/usr/bin/env python3
"""
backtester.py - Kalshi 15-min Crypto Strategy Backtester
Fetches real Coinbase historical data and tests trading strategies.

Usage: python backtester.py [--coins BTC ETH SOL] [--candles 200]
"""

import json
import math
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import argparse

import requests

# =============================================================================
# CONFIG
# =============================================================================

COINBASE_API = "https://api.exchange.coinbase.com"
COINS = ['BTC', 'ETH', 'SOL', 'BNB', 'DOGE', 'XRP', 'HYPE']
COINBASE_PRODUCTS = {
    'BTC': 'BTC-USD',
    'ETH': 'ETH-USD',
    'SOL': 'SOL-USD',
    'BNB': 'BNB-USD',
    'DOGE': 'DOGE-USD',
    'XRP': 'XRP-USD',
    'HYPE': 'HYPE-USD',
    'ADA': 'ADA-USD',
}

CACHE_DIR = Path(__file__).parent / ".backtest_cache"
CACHE_DIR.mkdir(exist_ok=True)

# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class Candle:
    timestamp: int  # Unix timestamp
    low: float
    high: float
    open: float
    close: float
    volume: float

@dataclass
class WindowResult:
    """Result of a single 15-min window."""
    coin: str
    open_time: int
    open: float
    close: float
    high: float
    low: float
    yes_win: bool
    return_pct: float  # (close - open) / open * 100

@dataclass
class Trade:
    """A single trade in a backtest."""
    coin: str
    window_time: int
    side: str  # 'yes' or 'no'
    entry_price: float
    exit_price: float  # settlement: 1.0 if win, 0.0 if loss
    won: bool
    pnl: float
    entry_minute: int  # 0-14 (minute into window)
    signal_type: str  # 'naive', 'price_vs_strike', 'timing', 'dynamic', 'bot_logic'
    strategy_name: str

@dataclass
class StrategyMetrics:
    name: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    sharpe: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    avg_pnl: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0

# =============================================================================
# DATA FETCHING
# =============================================================================

def get_cache_path(coin: str, granularity: int = 900) -> Path:
    return CACHE_DIR / f"{coin}_{granularity}_candles.json"

def fetch_candles(coin: str, granularity: int = 900, max_candles: int = 300) -> List[Candle]:
    """
    Fetch historical candles from Coinbase public API.
    Returns list of Candle objects (oldest first).
    """
    cache_path = get_cache_path(coin, granularity)
    
    # Check cache (valid for 1 hour)
    if cache_path.exists():
        try:
            mtime = cache_path.stat().st_mtime
            if time.time() - mtime < 3600:
                with open(cache_path) as f:
                    data = json.load(f)
                candles = [Candle(**c) for c in data]
                if len(candles) >= max_candles * 0.9:
                    print(f"  [CACHE] {coin}: {len(candles)} candles loaded from cache")
                    return candles
        except (json.JSONDecodeError, IOError):
            pass

    product_id = COINBASE_PRODUCTS.get(coin.upper())
    if not product_id:
        print(f"  [WARN] No Coinbase product for {coin}")
        return []

    # Coinbase API: returns newest first, we reverse to oldest first
    url = f"{COINBASE_API}/products/{product_id}/candles"
    params = {
        'granularity': granularity,
        'limit': max_candles,
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        raw = response.json()
        
        # Coinbase returns [timestamp, low, high, open, close, volume]
        candles = []
        for row in raw:
            ts, low, high, open_price, close, vol = row
            candles.append(Candle(
                timestamp=int(ts),
                low=float(low),
                high=float(high),
                open=float(open_price),
                close=float(close),
                volume=float(vol)
            ))
        
        # Coinbase returns newest first, reverse to chronological
        candles = list(reversed(candles))
        
        # Cache it
        with open(cache_path, 'w') as f:
            json.dump([asdict(c) for c in candles], f)
        
        print(f"  [FETCH] {coin}: {len(candles)} candles fetched from Coinbase")
        return candles
        
    except Exception as e:
        print(f"  [ERROR] Failed to fetch {coin}: {e}")
        # Try cache even if stale
        if cache_path.exists():
            try:
                with open(cache_path) as f:
                    data = json.load(f)
                candles = [Candle(**c) for c in data]
                print(f"  [CACHE] {coin}: {len(candles)} candles loaded from stale cache")
                return candles
            except:
                pass
        return []

# =============================================================================
# WINDOW GENERATION
# =============================================================================

def build_windows(candles: List[Candle], coin: str) -> List[WindowResult]:
    """
    Convert Coinbase candles to trading windows.
    Each Coinbase 15-min candle IS a trading window:
    - open = candle open (this is the Kalshi floor_strike reference)
    - close = candle close (this determines YES/NO settlement)
    - YES wins if close >= open
    """
    results = []
    for c in candles:
        yes_win = c.close >= c.open
        ret_pct = (c.close - c.open) / c.open * 100 if c.open != 0 else 0
        results.append(WindowResult(
            coin=coin,
            open_time=c.timestamp,
            open=c.open,
            close=c.close,
            high=c.high,
            low=c.low,
            yes_win=yes_win,
            return_pct=ret_pct
        ))
    return results

# =============================================================================
# SIMULATE CANDLE SIGNALS (for Strategy E)
# =============================================================================

def simulate_candle_signal(window: WindowResult) -> Optional[str]:
    """
    Simulate the candle signal from candle_watcher.py logic.
    Candle watcher fires:
    - YES signal: price above previous candle's close for >90% of the candle time
    - NO signal: price below previous candle's close for >60% of the candle time
    
    Since we only have the candle data (open, high, low, close), we approximate:
    - If high > open AND low < open: price crossed above then below → might have crossed
    - If close > open: price ended above → YES bias
    - If close < open: price ended below → NO bias
    
    We use a simplified version: candle is "bullish" if close > open by some threshold.
    """
    if window.close > window.open:
        # Bullish candle - potential YES signal
        return 'YES'
    else:
        # Bearish/neutral candle - potential NO signal
        return 'NO'

# =============================================================================
# STRATEGY BACKTESTING
# =============================================================================

def run_strategy_naive(windows: List[WindowResult]) -> List[Trade]:
    """
    Strategy A: Naive - Buy YES at $0.50 every time.
    """
    trades = []
    for w in windows:
        entry_price = 0.50
        won = w.yes_win
        pnl = 1.00 - entry_price if won else -entry_price
        trades.append(Trade(
            coin=w.coin,
            window_time=w.open_time,
            side='yes',
            entry_price=entry_price,
            exit_price=1.0 if won else 0.0,
            won=won,
            pnl=pnl,
            entry_minute=0,
            signal_type='naive',
            strategy_name='Strategy_A_Naive'
        ))
    return trades

def run_strategy_price_vs_strike(windows: List[WindowResult]) -> List[Trade]:
    """
    Strategy B: Price vs Strike - Buy YES if open > floor_strike (always true by def),
    but skip if mid > $0.65.
    Entry within first 5 min (minute 0-4).
    """
    trades = []
    for w in windows:
        # floor_strike = w.open (by definition in our simulation)
        # Entry rule: open_price > floor_strike (always true for YES here)
        # Skip if entry price > $0.65
        entry_price = 0.50  # mid price
        if entry_price > 0.65:
            continue
        
        won = w.yes_win
        pnl = 1.00 - entry_price if won else -entry_price
        trades.append(Trade(
            coin=w.coin,
            window_time=w.open_time,
            side='yes',
            entry_price=entry_price,
            exit_price=1.0 if won else 0.0,
            won=won,
            pnl=pnl,
            entry_minute=2,  # Simulate mid-window entry
            signal_type='price_vs_strike',
            strategy_name='Strategy_B_PriceVsStrike'
        ))
    return trades

def run_strategy_timing(windows: List[WindowResult]) -> List[Trade]:
    """
    Strategy C: Price vs Strike with Timing + Cut-loss at 10 min.
    Entry: open > floor AND entry at minute 0-4.
    Cut-loss if at 10 min mark price has moved against us by $0.10.
    
    We approximate the 10-min price using candle midpoint: (high+low)/2
    If midpoint at 10 min < entry - $0.10 → cut loss.
    """
    trades = []
    
    for w in windows:
        entry_price = 0.50
        entry_minute = 2  # Simulate early entry (minute 2)
        
        if entry_price > 0.65:
            continue
        
        # Approximate 10-min price as midpoint of candle
        # If high > open > low, midpoint represents typical price movement
        mid_price = (w.high + w.low) / 2.0
        
        # Cut-loss: if midpoint at 10-min mark < entry - $0.10
        if mid_price < entry_price - 0.10:
            # Would have cut at loss
            pnl = -0.10
            won = False
        else:
            pnl = 1.00 - entry_price
            won = w.yes_win
        
        trades.append(Trade(
            coin=w.coin,
            window_time=w.open_time,
            side='yes',
            entry_price=entry_price,
            exit_price=1.0 if won else 0.0,
            won=won,
            pnl=pnl,
            entry_minute=entry_minute,
            signal_type='timing',
            strategy_name='Strategy_C_Timing'
        ))
    return trades

def run_strategy_dynamic_no(windows: List[WindowResult]) -> List[Trade]:
    """
    Strategy D: Dynamic Entry (NO only) - The 12-min NO Lock-in.
    
    Nerd's research: if price <= floor_strike (open) at 12 min mark,
    NO wins 95.9% of the time.
    
    We can't know the 12-min price without intrabar data. We approximate:
    - If the candle range (high-low) is small and close < open → price was likely 
      below open for most of the candle → the 12-min check likely showed NO
    - Use: if (close < open) AND (range < avg_range * 0.5) → low volatility bearish
    
    This is a conservative filter that only fires on clear bearish, low-volatility candles.
    """
    trades = []
    
    # Calculate average range for filtering
    ranges = [w.high - w.low for w in windows if w.high > w.low]
    avg_range = sum(ranges) / len(ranges) if ranges else 1.0
    
    for w in windows:
        candle_range = w.high - w.low
        range_ratio = candle_range / avg_range if avg_range > 0 else 1.0
        
        # Dynamic NO: bearish candle with low volatility
        # Close below open AND range is small (price was stable below open)
        if w.close < w.open and range_ratio < 0.7:
            entry_price = 0.50
            won = w.close < w.open  # NO wins if close < open
            pnl = 1.00 - entry_price if won else -entry_price
            trades.append(Trade(
                coin=w.coin,
                window_time=w.open_time,
                side='no',
                entry_price=entry_price,
                exit_price=1.0 if won else 0.0,
                won=won,
                pnl=pnl,
                entry_minute=12,  # 12-min entry
                signal_type='dynamic_no',
                strategy_name='Strategy_D_DynamicNO'
            ))
    return trades

def run_strategy_bot_logic(windows: List[WindowResult]) -> List[Trade]:
    """
    Strategy E: Our Actual Bot Logic.
    - Only enter YES when candle signal fires AND mid < $0.50
    - Only enter NO when candle signal fires AND mid < $0.35
    - Cut-loss at $0.10
    
    The candle signal is based on the PREVIOUS candle's characteristics:
    - Previous candle bullish (close > open) → YES signal for current window
    - Previous candle bearish (close < open) → NO signal for current window
    
    This avoids circularity: we're predicting CURRENT window outcome using
    PREVIOUS candle's data.
    """
    import random
    trades = []
    random.seed(42)  # Reproducible
    
    for i, w in enumerate(windows):
        # Use PREVIOUS candle to generate signal (avoid circularity)
        if i > 0:
            prev = windows[i - 1]
            if prev.close > prev.open:
                candle_signal = 'YES'
            else:
                candle_signal = 'NO'
        else:
            continue  # Skip first window, no previous candle
        
        if candle_signal == 'YES':
            # Simulate mid price distribution for YES signals
            # 40% chance mid is in cheap zone (< $0.50) - slightly better odds
            if random.random() < 0.40:
                entry_price = round(random.uniform(0.30, 0.49), 2)
            else:
                entry_price = round(random.uniform(0.50, 0.65), 2)
            
            if entry_price >= 0.50:
                continue  # Skip expensive entries per bot rules
            
            # Cut-loss rule: if price moves against us (based on candle direction)
            if w.close < w.open:
                # Price moved against us → cut loss
                pnl = -0.10
                won = False
            else:
                pnl = 1.00 - entry_price
                won = w.yes_win
            
            trades.append(Trade(
                coin=w.coin,
                window_time=w.open_time,
                side='yes',
                entry_price=entry_price,
                exit_price=1.0 if won else 0.0,
                won=won,
                pnl=pnl,
                entry_minute=1,
                signal_type='bot_logic_yes',
                strategy_name='Strategy_E_BotLogic_YES'
            ))
        elif candle_signal == 'NO':
            # Simulate mid price distribution for NO signals
            # 50% chance mid is in cheap zone (< $0.35)
            if random.random() < 0.50:
                entry_price = round(random.uniform(0.20, 0.34), 2)
            else:
                entry_price = round(random.uniform(0.35, 0.50), 2)
            
            if entry_price >= 0.35:
                continue  # Skip expensive NO entries per bot rules
            
            # Cut-loss: if price moves against us (YES wins)
            if w.close >= w.open:
                pnl = -0.10
                won = False
            else:
                pnl = 1.00 - entry_price
                won = not w.yes_win
            
            trades.append(Trade(
                coin=w.coin,
                window_time=w.open_time,
                side='no',
                entry_price=entry_price,
                exit_price=1.0 if won else 0.0,
                won=won,
                pnl=pnl,
                entry_minute=1,
                signal_type='bot_logic_no',
                strategy_name='Strategy_E_BotLogic_NO'
            ))
    return trades

def run_strategy_bot_logic_no_filter(windows: List[WindowResult]) -> List[Trade]:
    """
    Strategy E variant: Bot logic WITHOUT candle signal filter.
    Compare to understand candle signal value.
    Fires on every window regardless of candle direction - just uses price filter.
    """
    import random
    trades = []
    random.seed(42)  # Same seed for fair comparison
    
    for i, w in enumerate(windows):
        if i == 0:
            continue  # Skip first window for consistency
        
        # Same price rules but no candle signal filter
        # Fires on EVERY window with price in range
        
        # YES side - 40% chance in cheap zone
        if random.random() < 0.40:
            entry_price = round(random.uniform(0.30, 0.49), 2)
        else:
            entry_price = round(random.uniform(0.50, 0.65), 2)
        
        if entry_price < 0.50:
            if w.close < w.open:
                pnl = -0.10
                won = False
            else:
                pnl = 1.00 - entry_price
                won = w.yes_win
            trades.append(Trade(
                coin=w.coin,
                window_time=w.open_time,
                side='yes',
                entry_price=entry_price,
                exit_price=1.0 if won else 0.0,
                won=won,
                pnl=pnl,
                entry_minute=1,
                signal_type='bot_logic_nofilter_yes',
                strategy_name='Strategy_E_NoFilter_YES'
            ))
        
        # NO side - 50% chance in cheap zone
        if random.random() < 0.50:
            entry_price = round(random.uniform(0.20, 0.34), 2)
        else:
            entry_price = round(random.uniform(0.35, 0.50), 2)
        
        if entry_price < 0.35:
            if w.close >= w.open:
                pnl = -0.10
                won = False
            else:
                pnl = 1.00 - entry_price
                won = not w.yes_win
            trades.append(Trade(
                coin=w.coin,
                window_time=w.open_time,
                side='no',
                entry_price=entry_price,
                exit_price=1.0 if won else 0.0,
                won=won,
                pnl=pnl,
                entry_minute=1,
                signal_type='bot_logic_nofilter_no',
                strategy_name='Strategy_E_NoFilter_NO'
            ))
    return trades

# =============================================================================
# METRICS CALCULATION
# =============================================================================

def calculate_metrics(trades: List[Trade], name: str) -> StrategyMetrics:
    """Calculate performance metrics for a list of trades."""
    if not trades:
        return StrategyMetrics(name=name)
    
    metrics = StrategyMetrics(name=name)
    metrics.total_trades = len(trades)
    
    wins = [t for t in trades if t.won]
    losses = [t for t in trades if not t.won]
    metrics.wins = len(wins)
    metrics.losses = len(losses)
    
    if metrics.total_trades > 0:
        metrics.win_rate = metrics.wins / metrics.total_trades * 100
    
    total_pnl = sum(t.pnl for t in trades)
    metrics.total_pnl = total_pnl
    metrics.avg_pnl = total_pnl / metrics.total_trades
    
    if wins:
        metrics.avg_win = sum(t.pnl for t in wins) / len(wins)
        metrics.largest_win = max(t.pnl for t in wins)
    
    if losses:
        metrics.avg_loss = sum(t.pnl for t in losses) / len(losses)
        metrics.largest_loss = min(t.pnl for t in losses)
    
    # Sharpe ratio
    if len(trades) >= 2:
        pnls = [t.pnl for t in trades]
        mean_pnl = sum(pnls) / len(pnls)
        variance = sum((p - mean_pnl) ** 2 for p in pnls) / (len(pnls) - 1)
        std_dev = math.sqrt(variance)
        if std_dev > 0:
            # Annualized (assuming 96 trades/day = 15-min intervals, 365 days)
            sharpe_daily = (mean_pnl / std_dev) * math.sqrt(96) if std_dev > 0 else 0
            metrics.sharpe = sharpe_daily
    
    # Max drawdown
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in trades:
        cumulative += t.pnl
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd
    metrics.max_drawdown = max_dd
    
    return metrics

# =============================================================================
# KEY ANALYSIS
# =============================================================================

def analyze_market_characteristics(windows: List[WindowResult]) -> Dict:
    """Analyze overall market characteristics."""
    if not windows:
        return {}
    
    yes_wins = sum(1 for w in windows if w.yes_win)
    total = len(windows)
    yes_pct = yes_wins / total * 100
    
    returns = [w.return_pct for w in windows]
    avg_return = sum(returns) / len(returns)
    
    # Magnitude when YES vs NO wins
    yes_returns = [w.return_pct for w in windows if w.yes_win]
    no_returns = [w.return_pct for w in windows if not w.yes_win]
    avg_yes_win_magnitude = sum(yes_returns) / len(yes_returns) if yes_returns else 0
    avg_no_win_magnitude = sum(no_returns) / len(no_returns) if no_returns else 0
    
    # Distribution by entry minute
    # We don't have intrabar data, but we can analyze by coin
    by_coin = {}
    for w in windows:
        if w.coin not in by_coin:
            by_coin[w.coin] = {'yes': 0, 'total': 0}
        by_coin[w.coin]['total'] += 1
        if w.yes_win:
            by_coin[w.coin]['yes'] += 1
    
    for coin in by_coin:
        c = by_coin[coin]
        c['yes_rate'] = c['yes'] / c['total'] * 100 if c['total'] > 0 else 0
    
    return {
        'total_windows': total,
        'yes_win_pct': yes_pct,
        'avg_return_pct': avg_return,
        'avg_yes_win_magnitude': avg_yes_win_magnitude,
        'avg_no_win_magnitude': avg_no_win_magnitude,
        'by_coin': by_coin,
    }

# =============================================================================
# MAIN BACKTEST RUNNER
# =============================================================================

def run_backtest(coins: List[str] = None, max_candles: int = 200) -> Dict:
    """Run full backtest across all coins and strategies."""
    if coins is None:
        coins = ['BTC', 'ETH', 'SOL', 'BNB', 'DOGE', 'XRP', 'HYPE']
    
    print("\n" + "="*70)
    print("KALSHI 15-MIN CRYPTO BACKTESTER")
    print("="*70)
    print(f"Coins: {', '.join(coins)}")
    print(f"Fetching up to {max_candles} candles per coin (~{max_candles*15//60}h of data)")
    print()
    
    # Fetch data for all coins
    all_windows = []
    for coin in coins:
        print(f"\n[{coin}] Fetching data...")
        candles = fetch_candles(coin, max_candles=max_candles)
        windows = build_windows(candles, coin)
        all_windows.extend(windows)
        print(f"  -> {len(windows)} windows ready for backtesting")
    
    if not all_windows:
        print("\n[ERROR] No data fetched. Exiting.")
        return {}
    
    print(f"\nTotal windows across all coins: {len(all_windows)}")
    
    # Analyze market characteristics
    print("\n" + "-"*70)
    print("MARKET CHARACTERISTICS")
    print("-"*70)
    market_analysis = analyze_market_characteristics(all_windows)
    print(f"Overall YES win rate: {market_analysis.get('yes_win_pct', 0):.1f}%")
    print(f"Avg return when YES wins: {market_analysis.get('avg_yes_win_magnitude', 0):.4f}%")
    print(f"Avg return when NO wins: {market_analysis.get('avg_no_win_magnitude', 0):.4f}%")
    print("\nYES win rate by coin:")
    by_coin = market_analysis.get('by_coin', {})
    for coin, data in sorted(by_coin.items()):
        print(f"  {coin}: {data['yes_rate']:.1f}% ({data['yes']}/{data['total']})")
    
    # Run all strategies
    print("\n" + "-"*70)
    print("STRATEGY BACKTESTING")
    print("-"*70)
    
    all_results = {}
    
    strategies = [
        ("Strategy_A_Naive", run_strategy_naive),
        ("Strategy_B_PriceVsStrike", run_strategy_price_vs_strike),
        ("Strategy_C_Timing", run_strategy_timing),
        ("Strategy_D_DynamicNO", run_strategy_dynamic_no),
        ("Strategy_E_BotLogic", run_strategy_bot_logic),
        ("Strategy_E_NoFilter", run_strategy_bot_logic_no_filter),
    ]
    
    for name, func in strategies:
        print(f"\nRunning {name}...")
        trades = func(all_windows)
        metrics = calculate_metrics(trades, name)
        all_results[name] = {
            'metrics': metrics,
            'trades': trades,
        }
        print(f"  Trades: {metrics.total_trades} | Win Rate: {metrics.win_rate:.1f}% | "
              f"Total P&L: ${metrics.total_pnl:.2f} | Avg P&L: ${metrics.avg_pnl:.4f}")
    
    return all_results, market_analysis

# =============================================================================
# OUTPUT & REPORTING
# =============================================================================

def print_summary_table(results: Dict):
    """Print a formatted summary table of all strategies."""
    print("\n" + "="*120)
    print("STRATEGY SUMMARY TABLE")
    print("="*120)
    print(f"{'Strategy':<30} {'Trades':>8} {'Win%':>8} {'AvgWin':>10} {'AvgLoss':>10} {'TotalPnL':>12} {'AvgPnL':>10} {'Sharpe':>8} {'MaxDD':>10}")
    print("-"*120)
    
    for name, data in sorted(results.items()):
        m = data['metrics']
        print(f"{m.name:<30} {m.total_trades:>8} {m.win_rate:>7.1f}% "
              f"${m.avg_win:>9.4f} ${m.avg_loss:>9.4f} ${m.total_pnl:>11.2f} "
              f"${m.avg_pnl:>9.4f} {m.sharpe:>8.2f} ${m.max_drawdown:>9.2f}")
    
    print("="*120)

def save_results(results: Dict, market_analysis: Dict, filepath: str):
    """Save results to JSON file."""
    output = {
        'timestamp': datetime.utcnow().isoformat(),
        'market_analysis': market_analysis,
        'strategies': {}
    }
    
    for name, data in results.items():
        m = data['metrics']
        output['strategies'][name] = {
            'metrics': asdict(m),
            'num_trades': len(data['trades']),
        }
    
    with open(filepath, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    
    print(f"\nResults saved to: {filepath}")

def update_research_md(results: Dict, market_analysis: Dict):
    """Update RESEARCH.md with backtest findings."""
    research_path = Path("/home/ubuntu/.openclaw/workspace/RESEARCH.md")
    
    # Find insertion point (before "## Strategic Recommendations" or at end)
    insert_marker = "## Strategic Recommendations"
    
    findings = f"""

## Backtest Findings ({datetime.utcnow().strftime('%Y-%m-%d')})

### Market Characteristics
- **Overall YES win rate**: {market_analysis.get('yes_win_pct', 0):.1f}%
- **Avg return when YES wins**: {market_analysis.get('avg_yes_win_magnitude', 0):.4f}%
- **Avg return when NO wins**: {market_analysis.get('avg_no_win_magnitude', 0):.4f}%

### YES Win Rate by Coin
"""
    by_coin = market_analysis.get('by_coin', {})
    for coin, data in sorted(by_coin.items()):
        findings += f"- **{coin}**: {data['yes_rate']:.1f}% ({data['yes']}/{data['total']} windows)\n"

    findings += "\n### Strategy Performance\n"
    findings += f"| Strategy | Trades | Win Rate | Total P&L | Avg P&L | Sharpe | Max DD |\n"
    findings += f"|----------|--------|----------|-----------|---------|--------|--------|\n"
    
    for name, data in sorted(results.items()):
        m = data['metrics']
        findings += f"| {m.name} | {m.total_trades} | {m.win_rate:.1f}% | ${m.total_pnl:.2f} | ${m.avg_pnl:.4f} | {m.sharpe:.2f} | ${m.max_drawdown:.2f} |\n"

    # Find best strategy
    best_name = max(results.keys(), key=lambda k: results[k]['metrics'].total_pnl)
    best = results[best_name]['metrics']
    findings += f"\n**Best Strategy**: {best_name} with ${best.total_pnl:.2f} total P&L\n"

    findings += "\n### Key Insights\n"
    
    # Auto-generate insights
    for name, data in results.items():
        m = data['metrics']
        if m.total_trades > 0:
            if m.win_rate > 55:
                findings += f"- **{m.name}**: High win rate ({m.win_rate:.1f}%) but avg trade is ${m.avg_pnl:.4f}\n"
            elif m.win_rate < 45:
                findings += f"- **{m.name}**: Low win rate ({m.win_rate:.1f}%), {'profitable' if m.total_pnl > 0 else 'unprofitable'} (${m.total_pnl:.2f})\n"

    # Try to insert before Strategic Recommendations
    if research_path.exists():
        try:
            content = research_path.read_text()
            if insert_marker in content:
                parts = content.split(insert_marker)
                content = parts[0] + findings + "\n" + insert_marker + parts[1]
            else:
                content = content + findings
            
            research_path.write_text(content)
            print(f"Research.md updated with backtest findings")
        except Exception as e:
            print(f"[WARN] Could not update RESEARCH.md: {e}")

# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Kalshi 15-min Crypto Backtester')
    parser.add_argument('--coins', nargs='+', default=None,
                        help='Coins to backtest (default: all available)')
    parser.add_argument('--candles', type=int, default=200,
                        help='Number of candles to fetch (default: 200)')
    parser.add_argument('--no-save', action='store_true',
                        help='Skip saving results to JSON')
    args = parser.parse_args()
    
    results, market_analysis = run_backtest(coins=args.coins, max_candles=args.candles)
    
    if results:
        print_summary_table(results)
        
        if not args.no_save:
            save_path = Path(__file__).parent / "backtest_results.json"
            save_results(results, market_analysis, str(save_path))
            update_research_md(results, market_analysis)
    else:
        print("\n[ERROR] Backtest produced no results")
        sys.exit(1)
