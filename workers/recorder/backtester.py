#!/usr/bin/env python3
"""
Simple Mean-Reversion Backtester
Loads 1-min OHLCV historical data and backtests a mean-reversion strategy.

Strategy: If price drops X% below rolling avg → BUY
          If price rises Y% above rolling avg → SELL
          Otherwise → HOLD

Outputs: P&L curve, win rate, max drawdown, summary stats
"""

import json
import math
import sys
import os
from datetime import datetime

# ─── CONFIG ───────────────────────────────────────────────────────────────────
HIST_DIR = "/home/ubuntu/.openclaw/workspace/workers/recorder/data/historical"

# Default strategy params
DEFAULT_LOOKBACK = 20    # rolling avg lookback in minutes
DEFAULT_BUY_THRESH = 0.2  # % below avg to buy
DEFAULT_SELL_THRESH = 0.2  # % above avg to sell
DEFAULT_STOP_LOSS = 0.5   # % adverse move to trigger stop loss
DEFAULT_POSITION_SIZE = 100  # $ per trade

# ─── LOAD DATA ────────────────────────────────────────────────────────────────
def load_coin(coin: str):
    path = os.path.join(HIST_DIR, f"{coin}_1min.json")
    if not os.path.exists(path):
        print(f"ERROR: {path} not found. Pull historical data first.")
        sys.exit(1)
    with open(path) as f:
        raw = json.load(f)
    print(f"Loaded {len(raw)} bars for {coin}")
    return raw

# ─── STRATEGY ─────────────────────────────────────────────────────────────────
def run_backtest(bars, lookback=DEFAULT_LOOKBACK, buy_thresh=DEFAULT_BUY_THRESH,
                 sell_thresh=DEFAULT_SELL_THRESH, stop_loss=DEFAULT_STOP_LOSS,
                 position_size=DEFAULT_POSITION_SIZE, coin_name="COIN"):
    """
    Mean-reversion backtest on 1-min bars.
    
    Signals:
      - BUY:  price < rolling_avg * (1 - buy_thresh/100)
      - SELL: price > rolling_avg * (1 + sell_thresh/100)  AND in position
      - STOP: price moves against position by stop_loss %
    
    Returns dict with trade log, equity curve, stats.
    """
    
    # Compute rolling averages
    closes = [b['close'] for b in bars]
    highs = [b['high'] for b in bars]
    lows = [b['low'] for b in bars]
    volumes = [b.get('volume', 0) for b in bars]
    timestamps = [b['timestamp'] for b in bars]
    
    rolling_avgs = []
    for i in range(len(closes)):
        if i < lookback - 1:
            rolling_avgs.append(None)
        else:
            avg = sum(closes[i-lookback+1:i+1]) / lookback
            rolling_avgs.append(avg)
    
    # Backtest simulation
    trades = []       # list of {entry_time, exit_time, entry_price, exit_price, pnl, pnl_pct, side}
    equity = [position_size]  # start with $100
    position = 0      # 0=flat, 1=long
    entry_price = 0
    entry_time = 0
    
    buy_signals = 0
    sell_signals = 0
    stop_losses = 0
    
    for i in range(lookback, len(closes)):
        price = closes[i]
        avg = rolling_avgs[i]
        if avg is None:
            continue
        
        below_pct = (avg - price) / avg * 100
        above_pct = (price - avg) / avg * 100
        
        if position == 0:
            # Check for buy signal
            if below_pct >= buy_thresh:
                position = 1
                entry_price = price
                entry_time = timestamps[i]
                buy_signals += 1
        
        elif position == 1:
            # Check for sell signal
            if above_pct >= sell_thresh:
                pnl = (price - entry_price) * (position_size / entry_price)
                trades.append({
                    'entry_time': entry_time,
                    'exit_time': timestamps[i],
                    'entry_price': entry_price,
                    'exit_price': price,
                    'pnl': pnl,
                    'pnl_pct': (price - entry_price) / entry_price * 100,
                    'side': 'LONG',
                    'exit_reason': 'SIGNAL'
                })
                equity.append(equity[-1] + pnl)
                position = 0
                sell_signals += 1
            
            # Check for stop loss
            elif (entry_price - price) / entry_price * 100 >= stop_loss:
                pnl = (price - entry_price) * (position_size / entry_price)
                trades.append({
                    'entry_time': entry_time,
                    'exit_time': timestamps[i],
                    'entry_price': entry_price,
                    'exit_price': price,
                    'pnl': pnl,
                    'pnl_pct': (price - entry_price) / entry_price * 100,
                    'side': 'LONG',
                    'exit_reason': 'STOP_LOSS'
                })
                equity.append(equity[-1] + pnl)
                position = 0
                stop_losses += 1
    
    # Close any open position at end
    if position == 1:
        price = closes[-1]
        pnl = (price - entry_price) * (position_size / entry_price)
        trades.append({
            'entry_time': entry_time,
            'exit_time': timestamps[-1],
            'entry_price': entry_price,
            'exit_price': price,
            'pnl': pnl,
            'pnl_pct': (price - entry_price) / entry_price * 100,
            'side': 'LONG',
            'exit_reason': 'END'
        })
        equity[-1] += pnl
        position = 0
    
    # ─── STATS ───────────────────────────────────────────────────────────────
    if not trades:
        print("No trades generated with these parameters.")
        return None
    
    pnls = [t['pnl'] for t in trades]
    total_pnl = sum(pnls)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    win_rate = len(wins) / len(trades) * 100
    
    # Max drawdown
    peak = equity[0]
    max_dd = 0
    max_dd_pct = 0
    for e in equity:
        if e > peak:
            peak = e
        dd = peak - e
        if dd > max_dd:
            max_dd = dd
            max_dd_pct = dd / peak * 100 if peak > 0 else 0
    
    # Max consecutive wins/losses
    streak = 0
    max_win_streak = 0
    max_loss_streak = 0
    for p in pnls:
        if p > 0:
            streak = streak + 1 if streak > 0 else 1
            max_win_streak = max(max_win_streak, streak)
        else:
            streak = streak - 1 if streak < 0 else -1
            max_loss_streak = max(max_loss_streak, abs(streak))
    
    # Sharpe-like (simple)
    mean_ret = sum(pnls) / len(pnls)
    std_ret = math.sqrt(sum((p - mean_ret)**2 for p in pnls) / len(pnls)) if len(pnls) > 1 else 0
    sharpe = (mean_ret / std_ret) if std_ret > 0 else 0
    
    # Profit factor
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_win / gross_loss if gross_loss > 0 else float('inf')
    
    # ─── PRINT RESULTS ────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  BACKTEST RESULTS: {coin_name} | Mean-Reversion Strategy")
    print(f"{'='*60}")
    print(f"  Lookback: {lookback} min | Buy: {buy_thresh}% below avg | Sell: {sell_thresh}% above avg")
    print(f"  Stop loss: {stop_loss}% | Position size: ${position_size}")
    print(f"")
    print(f"  ── Performance ──────────────────────────────────────────")
    print(f"  Total P&L:        ${total_pnl:.2f}")
    print(f"  Win rate:         {win_rate:.1f}% ({len(wins)} wins / {len(trades)} trades)")
    print(f"  Profit factor:    {profit_factor:.2f}")
    print(f"  Sharpe ratio:     {sharpe:.3f}")
    print(f"  Max drawdown:     ${max_dd:.2f} ({max_dd_pct:.2f}%)")
    print(f"  Max win streak:   {max_win_streak}")
    print(f"  Max loss streak:  {max_loss_streak}")
    print(f"  Avg trade P&L:   ${mean_ret:.2f} (std: ${std_ret:.2f})")
    print(f"")
    print(f"  ── Trade Breakdown ───────────────────────────────────────")
    print(f"  Buy signals:      {buy_signals}")
    print(f"  Sell signals:     {sell_signals}")
    print(f"  Stop losses:      {stop_losses}")
    print(f"  Avg win:          ${sum(wins)/len(wins):.2f}" if wins else "  Avg win:          N/A")
    print(f"  Avg loss:         ${sum(losses)/len(losses):.2f}" if losses else "  Avg loss:         N/A")
    print(f"  Largest win:      ${max(wins):.2f}" if wins else "  Largest win:      N/A")
    print(f"  Largest loss:     ${min(losses):.2f}" if losses else "  Largest loss:     N/A")
    print(f"")
    print(f"  ── Equity Curve ({len(equity)} data points) ──────────────────────────")
    print(f"  Starting equity:  ${equity[0]:.2f}")
    print(f"  Final equity:     ${equity[-1]:.2f}")
    print(f"  Total return:     {(equity[-1]-equity[0])/equity[0]*100:.2f}%")
    
    # Show last 10 trades
    print(f"\n  Last 10 trades:")
    print(f"  {'Entry Time':<20} {'Exit Time':<20} {'Entry $':>10} {'Exit $':>10} {'P&L $':>10} {'%':>8} {'Exit Reason'}")
    print(f"  {'-'*20} {'-'*20} {'-'*10} {'-'*10} {'-'*10} {'-'*8} {'-'*12}")
    for t in trades[-10:]:
        dt_entry = datetime.fromtimestamp(t['entry_time']).strftime('%Y-%m-%d %H:%M')
        dt_exit = datetime.fromtimestamp(t['exit_time']).strftime('%Y-%m-%d %H:%M')
        print(f"  {dt_entry:<20} {dt_exit:<20} {t['entry_price']:>10.4f} {t['exit_price']:>10.4f} {t['pnl']:>10.2f} {t['pnl_pct']:>7.3f}% {t['exit_reason']}")
    
    # ASCII equity chart (simple)
    print(f"\n  Equity curve (last 100 points):")
    if len(equity) > 1:
        display = equity[-100:] if len(equity) > 100 else equity
        min_e = min(display)
        max_e = max(display)
        range_e = max_e - min_e
        if range_e == 0:
            range_e = 1
        height = 12
        rows = []
        for level in range(height, -1, -1):
            threshold = min_e + (range_e / height) * level
            row = ""
            for e in display:
                if e >= threshold:
                    row += "█"
                else:
                    row += " "
            rows.append(f"  {'{:.1f}'.format(threshold):>8} |{row}")
        for r in rows:
            print(r)
        print(f"  {'>':>8} +{'-'*len(display)}+")
    
    print(f"\n{'='*60}")
    
    return {
        'total_pnl': total_pnl,
        'win_rate': win_rate,
        'profit_factor': profit_factor,
        'sharpe': sharpe,
        'max_drawdown': max_dd,
        'max_drawdown_pct': max_dd_pct,
        'num_trades': len(trades),
        'equity': equity,
        'trades': trades
    }


# ─── PARAMETER SCAN ───────────────────────────────────────────────────────────
def param_scan(coin, lookbacks=[10, 20, 30, 60], 
               buy_thresholds=[0.1, 0.2, 0.3, 0.5],
               sell_thresholds=[0.1, 0.2, 0.3, 0.5]):
    """Quick parameter scan to find best params."""
    bars = load_coin(coin)
    print(f"\n{'='*60}")
    print(f"  PARAMETER SCAN: {coin}")
    print(f"{'='*60}")
    
    best = None
    best_pnl = -999999
    
    for lb in lookbacks:
        for bt in buy_thresholds:
            for st in sell_thresholds:
                if bt > st:  # buy threshold should be <= sell for mean reversion
                    continue
                result = run_backtest(bars, lookback=lb, buy_thresh=bt, 
                                      sell_thresh=st, coin_name=f"{coin}(lb={lb},bt={bt},st={st})")
                if result and result['total_pnl'] > best_pnl:
                    best_pnl = result['total_pnl']
                    best = {'lookback': lb, 'buy_thresh': bt, 'sell_thresh': st, 'result': result}
                print()  # spacing
    
    if best:
        print(f"\n  ★ BEST PARAMS for {coin}: lookback={best['lookback']}, "
              f"buy={best['buy_thresh']}%, sell={best['sell_thresh']}%, "
              f"P&L=${best['result']['total_pnl']:.2f}, Win%={best['result']['win_rate']:.1f}%")
    
    return best


# ─── MAIN ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Mean-reversion backtester")
    parser.add_argument('--coin', type=str, default='BTC', help='Coin to backtest (BTC, ETH, etc.)')
    parser.add_argument('--lookback', type=int, default=20, help='Rolling avg lookback (minutes)')
    parser.add_argument('--buy', type=float, default=0.2, help='Buy threshold (% below avg)')
    parser.add_argument('--sell', type=float, default=0.2, help='Sell threshold (% above avg)')
    parser.add_argument('--stop', type=float, default=0.5, help='Stop loss threshold (%)')
    parser.add_argument('--size', type=float, default=100, help='Position size ($)')
    parser.add_argument('--scan', action='store_true', help='Run parameter scan')
    args = parser.parse_args()
    
    if args.scan:
        param_scan(args.coin)
    else:
        bars = load_coin(args.coin)
        run_backtest(bars, lookback=args.lookback, buy_thresh=args.buy,
                     sell_thresh=args.sell, stop_loss=args.stop,
                     position_size=args.size, coin_name=args.coin)
