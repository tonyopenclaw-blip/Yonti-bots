"""
backtest.py — Superbot Signal Backtest Framework

Tony's Rule: Before any new signal logic gets implemented, 
it MUST be backtested against historical data.

This module provides:
1. backtest_signal() - Test any signal type with specific conditions
2. test_new_signal() - Gatekeeper function that returns DEPLOY/HOLD/REJECT
3. Pre-built queries for existing signal types

THRESHOLDS (documented for review):
─────────────────────────────────────
WIN_RATE thresholds:
  - DEPLOY:   > 55% (above breakeven + edge)
  - HOLD:     45-55% (neutral zone, need more data)
  - REJECT:   < 45% (below breakeven)

PROFIT_FACTOR thresholds:
  - DEPLOY:   > 1.1 (10% expected edge over losses)
  - HOLD:     0.9-1.1 (neutral zone)
  - REJECT:   < 0.9 (negative expected value)

Why these thresholds?
  - Binary options on Kalshi pay $1 on YES, $0 on NO (or vice versa)
  - At 50/50 odds, profit_factor = 1.0 is breakeven
  - 55% WR with PF > 1.1 gives us a meaningful edge before slippage/fees
  - Conservative to avoid overfitting to small sample sizes
  - Can be tightened as we accumulate more data

Usage:
  from backtest import backtest_signal, test_new_signal, print_report
  
  # Test existing signal
  report = backtest_signal("candle_YES", {"conf": ">=97", "side": "YES"})
  print(print_report(report))
  
  # Test new proposed signal
  result = test_new_signal({"signal_type": "candle_NO", "conf": ">=99"})
  print(result)  # "DEPLOY" or "HOLD" or "REJECT"
"""

import json
import os
from typing import Optional

# Path to signal log
SIGNAL_LOG_PATH = os.path.join(os.path.dirname(__file__), "signal_log.json")

# Threshold constants
WR_DEPLOY = 0.55      # Win rate > 55% to deploy
WR_HOLD_LOW = 0.45    # Win rate 45-55% is neutral
PF_DEPLOY = 1.1       # Profit factor > 1.1 to deploy
PF_HOLD_LOW = 0.9     # Profit factor 0.9-1.1 is neutral


def load_signals() -> list:
    """Load signal_log.json and return list of signal dicts."""
    with open(SIGNAL_LOG_PATH, 'r') as f:
        return json.load(f)


def parse_condition(value: any, operator: str) -> bool:
    """
    Parse a condition like ">0.55" and apply to a value.
    Supports: >, <, >=, <=, ==, and bare value (equality)
    """
    if isinstance(value, str):
        value = value.strip('"\'')

    # Extract operator and comparison value
    # Check 2-char operators FIRST (>=, <=, ==)
    if isinstance(operator, str) and len(operator) >= 2:
        if operator.startswith('>='):
            op = '>='
            comp_value = operator[2:]
        elif operator.startswith('<='):
            op = '<='
            comp_value = operator[2:]
        elif operator.startswith('=='):
            op = '=='
            comp_value = operator[2:]
        elif operator.startswith('>'):
            op = '>'
            comp_value = operator[1:]
        elif operator.startswith('<'):
            op = '<'
            comp_value = operator[1:]
        elif operator.startswith('='):
            op = '=='
            comp_value = operator[1:]
        else:
            op = '=='
            comp_value = operator
    elif isinstance(operator, str) and len(operator) == 1:
        op = '=='
        comp_value = operator
    else:
        op = '=='
        comp_value = operator

    # Convert to numbers for comparison if possible
    try:
        value = float(value)
        comp_value = float(comp_value)
    except (TypeError, ValueError):
        # String comparison
        value = str(value).strip('"\'')
        comp_value = str(comp_value).strip('"\'')

    if op == '>':
        return value > comp_value
    elif op == '>=':
        return value >= comp_value
    elif op == '<':
        return value < comp_value
    elif op == '<=':
        return value <= comp_value
    else:  # == or =
        return value == comp_value


def matches_conditions(signal: dict, conditions: dict) -> bool:
    """
    Check if a signal matches all given conditions.
    
    Conditions format:
      {"conf": ">=97", "side": "YES", "won": True}
      
    Supports operators: >, <, >=, <=, == (or bare value for equality)
    """
    for field, condition in conditions.items():
        if field not in signal:
            return False
        
        value = signal[field]
        
        # Handle compound operator like ">=97"
        if isinstance(condition, str) and any(op in condition for op in ('>', '<', '=')):
            if not parse_condition(value, condition):
                return False
        # Handle True/False/None directly
        elif isinstance(condition, bool):
            if bool(value) != condition:
                return False
        elif condition is None:
            if value is not None:
                return False
        else:
            # Direct equality check
            if str(value).strip('"\'') != str(condition).strip('"\''):
                return False
    
    return True


def backtest_signal(signal_type: str, conditions: dict, 
                    include_blocked: bool = True,
                    include_taken: bool = True) -> dict:
    """
    Backtest a signal type with given conditions against historical data.
    
    Args:
        signal_type: Signal type to test (e.g., "candle_YES", "candle_NO")
        conditions: Dict of field conditions {"field": "operator", ...}
        include_blocked: Include BLOCKED signals (default True)
        include_taken: Include TAKEN signals (default True)
    
    Returns:
        dict with keys:
            - signal_type, conditions
            - total_signals, total_blocked, total_taken
            - settled_signals (only those with outcome)
            - wins, losses
            - win_rate
            - avg_win, avg_loss
            - profit_factor
            - roi_estimate
            - signals (list of matching signals)
    """
    signals = load_signals()
    
    # Filter by signal type and conditions
    matching = []
    for sig in signals:
        if sig.get("signal_type", "").lower() != signal_type.lower():
            continue
        
        # Check action filter
        action = sig.get("action", "").upper()
        if action == "BLOCKED" and not include_blocked:
            continue
        if action == "TAKEN" and not include_taken:
            continue
        if action == "PENDING":
            continue  # Skip pending, no outcome yet
        
        # Check conditions
        if matches_conditions(sig, conditions):
            matching.append(sig)
    
    # Calculate stats only on settled signals
    settled = [s for s in matching if s.get("won") is not None]
    wins = [s for s in settled if s.get("won") == True]
    losses = [s for s in settled if s.get("won") == False]
    
    total_trades = len(settled)
    win_count = len(wins)
    loss_count = len(losses)
    
    win_rate = win_count / total_trades if total_trades > 0 else 0.0
    
    # Calculate avg win/loss based on settlement_result
    # settlement_result = 1.0 means WON (got payout), 0.0 means LOST (got nothing, lost stake)
    # Net profit: WON = +$1, LOST = -$1
    avg_win = sum(1.0 for s in wins) / win_count if win_count > 0 else 0.0
    avg_loss = 1.0  # Each loss = -$1 (lost the stake)
    
    # Profit factor = gross wins / gross losses (in dollar terms)
    # Wins: each win pays +$1 (settlement_result=1)
    # Losses: each loss costs -$1 (settlement_result=0, so we lost our $1 stake)
    total_wins = sum(1.0 for s in wins)  # Each win = +$1 net
    total_losses = sum(1.0 for s in losses)  # Each loss = -$1 net
    profit_factor = total_wins / total_losses if total_losses > 0 else float('inf') if total_wins > 0 else 0.0
    
    # ROI estimate (simplified)
    roi_estimate = (total_wins - total_losses) / total_trades if total_trades > 0 else 0.0
    
    return {
        "signal_type": signal_type,
        "conditions": conditions,
        "total_signals": len(matching),
        "total_blocked": len([s for s in matching if s.get("action") == "BLOCKED"]),
        "total_taken": len([s for s in matching if s.get("action") == "TAKEN"]),
        "settled_signals": total_trades,
        "wins": win_count,
        "losses": loss_count,
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": profit_factor,
        "roi_estimate": roi_estimate,
        "signals": matching
    }


def test_new_signal(conditions: dict) -> str:
    """
    Gatekeeper function: Test proposed signal conditions against historical data.
    
    Returns:
        "DEPLOY"  if WR > 55% AND profit_factor > 1.1
        "HOLD"    if WR 45-55% OR profit_factor 0.9-1.1  
        "REJECT"  if WR < 45% OR profit_factor < 0.9
    
    This is the official gatekeeper before any signal logic change gets deployed.
    """
    # Determine signal_type from conditions if specified
    signal_type = conditions.get("signal_type", "candle_YES")
    
    report = backtest_signal(signal_type, conditions)
    
    wr = report["win_rate"]
    pf = report["profit_factor"]
    
    # Decision logic
    if wr < WR_HOLD_LOW or pf < PF_HOLD_LOW:
        return "REJECT"
    elif wr >= WR_DEPLOY and pf >= PF_DEPLOY:
        return "DEPLOY"
    else:
        return "HOLD"


def print_report(report: dict) -> str:
    """Format and return a human-readable backtest report."""
    lines = [
        f"\n{'='*60}",
        f"BACKTEST REPORT: {report['signal_type']}",
        f"{'='*60}",
        f"Conditions: {report['conditions']}",
        f"",
        f"Signal Counts:",
        f"  Total matching:   {report['total_signals']}",
        f"  BLOCKED:          {report['total_blocked']}",
        f"  TAKEN:            {report['total_taken']}",
        f"  Settled:          {report['settled_signals']}",
        f"",
        f"Performance (on settled signals):",
        f"  Wins:             {report['wins']}",
        f"  Losses:           {report['losses']}",
        f"  Win Rate:         {report['win_rate']:.1%}",
        f"  Avg Win:          ${report['avg_win']:.2f}",
        f"  Avg Loss:         ${report['avg_loss']:.2f}",
        f"  Profit Factor:    {report['profit_factor']:.2f}",
        f"  ROI Estimate:     ${report['roi_estimate']:.2f} per trade",
        f"",
    ]
    
    # Add verdict
    verdict = "DEPLOY" if report["win_rate"] >= WR_DEPLOY and report["profit_factor"] >= PF_DEPLOY else \
              "HOLD" if report["win_rate"] >= WR_HOLD_LOW and report["profit_factor"] >= PF_HOLD_LOW else "REJECT"
    
    lines.append(f"VERDICT: {verdict}")
    lines.append(f"{'='*60}\n")
    
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────
# PRE-BUILT BACKTEST QUERIES FOR EXISTING SIGNALS
# ─────────────────────────────────────────────────────────────────

def backtest_candle_yes(conf_threshold: int = 97) -> dict:
    """
    CANDLE_YES signal: mid < $0.55, conf >= 50
    Note: market_mid_at_signal is null in data, using conf as proxy
    """
    return backtest_signal("candle_YES", {
        "side": "YES",
        "conf": f">={conf_threshold}"
    })


def backtest_candle_no(conf_threshold: int = 99) -> dict:
    """
    CANDLE_NO signal: mid > $0.55, conf >= 50
    """
    return backtest_signal("candle_NO", {
        "side": "NO",
        "conf": f">={conf_threshold}"
    })


def backtest_stealth_tier1() -> dict:
    """
    STEALTH_TIER1: pvs > 0.3% OR obi > 0.5
    Note: pvs/obi fields not in current signal_log, this is a placeholder
    """
    # Since pvs/obi aren't in the data, we can't directly backtest
    return {
        "signal_type": "STEALTH_TIER1",
        "conditions": {"pvs": ">0.3", "obi": ">0.5"},
        "note": "pvs/obi fields not populated in signal_log - cannot backtest",
        "settled_signals": 0,
        "win_rate": 0,
        "profit_factor": 0,
        "signals": []
    }


def backtest_12min_no(yes_mid_threshold: float = 0.52, pullback_threshold: float = 5.0) -> dict:
    """
    12MIN_NO: yes_mid > $0.52, pullback > 5%
    Note: These fields not in current signal_log, placeholder
    """
    return {
        "signal_type": "12MIN_NO",
        "conditions": {"yes_mid": f">{yes_mid_threshold}", "pullback": f">{pullback_threshold}%"},
        "note": "yes_mid/pullback fields not in signal_log - cannot backtest",
        "settled_signals": 0,
        "win_rate": 0,
        "profit_factor": 0,
        "signals": []
    }


# ─────────────────────────────────────────────────────────────────
# BLOCKED SIGNALS ANALYSIS
# ─────────────────────────────────────────────────────────────────

def analyze_blocked_signals() -> dict:
    """
    Analyze the 6 BLOCKED signals to verify "would have won" claims.
    
    Blocked signals were rejected because "candle NO signals are unprofitable"
    But the actual outcomes show something different...
    """
    signals = load_signals()
    blocked = [s for s in signals if s.get("action") == "BLOCKED"]
    
    settled_blocked = [s for s in blocked if s.get("won") is not None]
    wins = [s for s in settled_blocked if s.get("won") == True]
    losses = [s for s in settled_blocked if s.get("won") == False]
    
    # Dollar terms: each win = +$1, each loss = -$1
    total_wins_dollar = len(wins) * 1.0
    total_losses_dollar = len(losses) * 1.0
    
    wr = len(wins) / len(settled_blocked) if settled_blocked else 0
    pf = total_wins_dollar / total_losses_dollar if total_losses_dollar > 0 else 0
    
    return {
        "total_blocked": len(blocked),
        "settled": len(settled_blocked),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": wr,
        "profit_factor": pf,
        "signals": blocked,
        "would_have_won": len(wins),
        "would_have_lost": len(losses)
    }


def print_blocked_analysis() -> str:
    """Print analysis of blocked signals."""
    analysis = analyze_blocked_signals()
    
    lines = [
        f"\n{'='*60}",
        f"BLOCKED SIGNALS ANALYSIS",
        f"{'='*60}",
        f"Total BLOCKED signals: {analysis['total_blocked']}",
        f"Settled:                {analysis['settled']}",
        f"",
        f"If we had taken them:",
        f"  Would have WON:       {analysis['would_have_won']}",
        f"  Would have LOST:      {analysis['would_have_lost']}",
        f"  Win Rate:             {analysis['win_rate']:.1%}",
        f"  Profit Factor:        {analysis['profit_factor']:.2f}",
        f"",
        f"Blocked signals:",
    ]
    
    for sig in analysis["signals"]:
        outcome = "WON" if sig.get("won") == True else "LOST" if sig.get("won") == False else "PENDING"
        settlement = sig.get("settlement_result")
        lines.append(f"  - {sig['coin']} {sig['signal_type']} @ {sig['timestamp'][11:19]} -> {outcome} (${settlement})")
    
    lines.append(f"{'='*60}\n")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────
# MAIN / CLI
# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n🎯 Superbot Backtest Framework")
    print("="*60)
    
    # Run pre-built queries
    print("\n[CANDLE_YES signals - conf >= 97]")
    r = backtest_candle_yes()
    print(print_report(r))
    
    print("\n[CANDLE_NO signals - conf >= 99]")
    r = backtest_candle_no()
    print(print_report(r))
    
    # Analyze blocked signals
    print(print_blocked_analysis())
    
    # Test the gatekeeper function
    print("\n[Gatekeeper Tests]")
    result = test_new_signal({"signal_type": "candle_YES", "conf": ">=97"})
    print(f"test_new_signal(candle_YES, conf>=97): {result}")
    
    result = test_new_signal({"signal_type": "candle_NO", "conf": ">=99"})
    print(f"test_new_signal(candle_NO, conf>=99): {result}")
    
    # Also test all taken vs blocked for candle_NO
    print("\n[All TAKEN candle_NO signals]")
    r = backtest_signal("candle_NO", {"conf": ">=99"}, include_blocked=False)
    print(print_report(r))
