#!/usr/bin/env python3
"""
🔍 Recorder Pattern Analyzer

Analyzes historical market data to find patterns that predict outcomes.
Specifically looks for the Tony insight:
"When price is above $0.50 for X% of the first 10 minutes, 
 it resolves YES Y% of the time"

Usage:
    python pattern_analysis.py                  # Run full analysis
    python pattern_analysis.py --min-samples 100  # Require min samples
    python pattern_analysis.py --json          # Output as JSON
"""

import argparse
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

# =============================================================================
# CONFIG
# =============================================================================

RECORDER_DATA = Path(__file__).parent / "data" / "market_data.jsonl"
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_DIR / f"pattern_analysis_{datetime.now(timezone.utc):%Y%m%d}.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


# =============================================================================
# DATA LOADING
# =============================================================================

def load_records() -> List[Dict]:
    """Load all market records from JSONL file."""
    if not RECORDER_DATA.exists():
        logger.warning(f"No data file found at {RECORDER_DATA}")
        return []
    
    records = []
    with open(RECORDER_DATA, "r") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                records.append(record)
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse line {line_num}: {e}")
    
    logger.info(f"Loaded {len(records)} records from {RECORDER_DATA}")
    return records


# =============================================================================
# PATTERN ANALYSIS
# =============================================================================

def analyze_pct_above_50_patterns(records: List[Dict], min_samples: int = 10) -> Dict:
    """
    The core Tony insight:
    "When price is above $0.50 for X% of the first 10 minutes, 
     it resolves YES Y% of the time"
    
    Build a lookup table: pct_above_50 bucket → win_rate
    """
    if not records:
        return {"error": "No data available", "buckets": {}}
    
    # Bucket pct_above_50 into 10% increments
    buckets = defaultdict(lambda: {"yes": 0, "no": 0, "total": 0})
    
    for record in records:
        if record.get("result") is None:
            continue
        
        total_samples = record.get("total_samples", 0)
        if total_samples < min_samples:
            continue
        
        pct_above_50 = record.get("pct_above_50", 0)
        result = record.get("result")  # "yes" or "no"
        
        # Bucket into 10% increments
        bucket = int(pct_above_50 * 10) / 10  # Round to nearest 0.1
        bucket = round(bucket, 1)
        
        buckets[bucket]["total"] += 1
        if result == "yes":
            buckets[bucket]["yes"] += 1
        else:
            buckets[bucket]["no"] += 1
    
    # Calculate win rates
    lookup_table = {}
    for bucket, counts in sorted(buckets.items()):
        total = counts["yes"] + counts["no"]
        if total >= min_samples:
            win_rate = counts["yes"] / total if total > 0 else 0
            lookup_table[f"{bucket:.0%}-{bucket+0.1:.0%}"] = {
                "win_rate": round(win_rate, 3),
                "yes_count": counts["yes"],
                "no_count": counts["no"],
                "total": total,
                "sample_size": total,
            }
    
    return {
        "analysis_type": "pct_above_50",
        "total_records": len(records),
        "records_with_results": sum(1 for r in records if r.get("result") is not None),
        "min_samples_required": min_samples,
        "buckets": lookup_table,
    }


def analyze_first_N_minutes(records: List[Dict], minutes: int = 10) -> Dict:
    """
    Analyze price action in the FIRST N minutes only.
    Tony's insight focuses on the first 10 minutes.
    """
    if not records:
        return {"error": "No data available", "buckets": {}}
    
    seconds_to_analyze = minutes * 60
    
    buckets = defaultdict(lambda: {"yes": 0, "no": 0})
    
    for record in records:
        if record.get("result") is None:
            continue
        
        samples = record.get("samples", [])
        if not samples:
            continue
        
        # Get samples from first N minutes only
        early_samples = [s for s in samples if s.get("second", 0) <= seconds_to_analyze]
        
        if not early_samples:
            continue
        
        # Calculate pct_above_50 for early samples
        above_50 = sum(1 for s in early_samples if s.get("yes_bid", 0) > 0.50)
        pct_above = above_50 / len(early_samples) if early_samples else 0
        
        result = record.get("result")
        
        # Bucket into 10% increments
        bucket = round(pct_above, 1)
        
        buckets[bucket]["yes" if result == "yes" else "no"] += 1
    
    # Calculate win rates
    lookup_table = {}
    for bucket, counts in sorted(buckets.items()):
        total = counts["yes"] + counts["no"]
        if total >= 5:
            win_rate = counts["yes"] / total if total > 0 else 0
            lookup_table[f"{bucket:.0%}"] = {
                "win_rate": round(win_rate, 3),
                "yes_count": counts["yes"],
                "no_count": counts["no"],
                "total": total,
            }
    
    return {
        "analysis_type": f"first_{minutes}_minutes",
        "total_records": len(records),
        "buckets": lookup_table,
    }


def analyze_price_trajectory(records: List[Dict]) -> Dict:
    """
    Analyze trajectory patterns:
    - Starts high, stays high → YES?
    - Starts low, goes high → YES?
    - Starts high, goes low → NO?
    - Starts low, stays low → NO?
    """
    if not records:
        return {"error": "No data available", "trajectories": {}}
    
    trajectory_stats = defaultdict(lambda: {"yes": 0, "no": 0})
    
    for record in records:
        if record.get("result") is None:
            continue
        
        samples = record.get("samples", [])
        if len(samples) < 5:
            continue
        
        # First 25% vs Last 25% of samples
        n = len(samples)
        first_quarter = samples[:max(1, n // 4)]
        last_quarter = samples[-max(1, n // 4):]
        
        first_avg = sum(s.get("yes_bid", 0) for s in first_quarter) / len(first_quarter)
        last_avg = sum(s.get("yes_bid", 0) for s in last_quarter) / len(last_quarter)
        
        # Classify trajectory
        if first_avg > 0.50 and last_avg > 0.50:
            traj = "HIGH_TO_HIGH"
        elif first_avg > 0.50 and last_avg <= 0.50:
            traj = "HIGH_TO_LOW"
        elif first_avg <= 0.50 and last_avg > 0.50:
            traj = "LOW_TO_HIGH"
        else:
            traj = "LOW_TO_LOW"
        
        result = record.get("result")
        trajectory_stats[traj]["yes" if result == "yes" else "no"] += 1
    
    # Calculate win rates for each trajectory
    trajectories = {}
    for traj, counts in sorted(trajectory_stats.items()):
        total = counts["yes"] + counts["no"]
        if total >= 3:
            win_rate = counts["yes"] / total if total > 0 else 0
            trajectories[traj] = {
                "win_rate": round(win_rate, 3),
                "yes_count": counts["yes"],
                "no_count": counts["no"],
                "total": total,
            }
    
    return {
        "analysis_type": "price_trajectory",
        "trajectories": trajectories,
    }


def analyze_by_coin(records: List[Dict]) -> Dict:
    """Break down win rates by coin (BTC, ETH, SOL, etc.)."""
    if not records:
        return {"error": "No data available", "by_coin": {}}
    
    coin_stats = defaultdict(lambda: {"yes": 0, "no": 0, "pct_above_50_sum": 0, "count": 0})
    
    for record in records:
        if record.get("result") is None:
            continue
        
        coin = record.get("coin", "UNK")
        result = record.get("result")
        pct_above_50 = record.get("pct_above_50", 0)
        
        coin_stats[coin]["yes" if result == "yes" else "no"] += 1
        coin_stats[coin]["pct_above_50_sum"] += pct_above_50
        coin_stats[coin]["count"] += 1
    
    by_coin = {}
    for coin, stats in sorted(coin_stats.items()):
        total = stats["yes"] + stats["no"]
        if total >= 3:
            win_rate = stats["yes"] / total if total > 0 else 0
            avg_pct_above = stats["pct_above_50_sum"] / stats["count"] if stats["count"] > 0 else 0
            by_coin[coin] = {
                "win_rate": round(win_rate, 3),
                "yes_count": stats["yes"],
                "no_count": stats["no"],
                "total": total,
                "avg_pct_above_50": round(avg_pct_above, 3),
            }
    
    return {
        "analysis_type": "by_coin",
        "by_coin": by_coin,
    }


def generate_trading_rules(analysis: Dict) -> List[Dict]:
    """
    Generate actionable trading rules from the analysis.
    This is the KEY OUTPUT - actionable rules for Superbot.
    """
    rules = []
    
    pct_analysis = analysis.get("pct_above_50", {})
    buckets = pct_analysis.get("buckets", {})
    
    if not buckets:
        return [{"condition": "NO_DATA", "action": "HOLD", "note": "Need more historical data to generate rules"}]
    
    # Find the bucket with highest win rate
    best_bucket = None
    best_win_rate = 0
    for bucket_range, data in buckets.items():
        wr = data["win_rate"]
        if wr > best_win_rate and data["sample_size"] >= 10:
            best_win_rate = wr
            best_bucket = bucket_range
    
    if best_bucket:
        rules.append({
            "condition": f"pct_above_50 in {best_bucket}",
            "action": "BUY_YES",
            "confidence": best_win_rate,
            "edge": best_win_rate - 0.5,  # Edge over 50/50
            "note": f"Historical win rate: {best_win_rate:.1%}",
        })
    
    # Find buckets with low win rate (potential shorts)
    worst_bucket = None
    worst_win_rate = 1.0
    for bucket_range, data in buckets.items():
        wr = data["win_rate"]
        if wr < worst_win_rate and data["sample_size"] >= 10:
            worst_win_rate = wr
            worst_bucket = bucket_range
    
    if worst_bucket:
        rules.append({
            "condition": f"pct_above_50 in {worst_bucket}",
            "action": "BUY_NO",
            "confidence": 1 - worst_win_rate,
            "edge": (1 - worst_win_rate) - 0.5,
            "note": f"Historical win rate for YES: {worst_win_rate:.1%} → NO wins {(1-worst_win_rate):.1%}",
        })
    
    # Find threshold-based rules
    # e.g., "if >70% above 50 in first 10 min → 75% win rate"
    for bucket_range, data in sorted(buckets.items()):
        if data["win_rate"] > 0.60 and data["sample_size"] >= 10:
            rules.append({
                "condition": f"pct_above_50 >= {bucket_range.split('-')[0]}",
                "action": "BUY_YES",
                "confidence": data["win_rate"],
                "edge": data["win_rate"] - 0.5,
                "sample_size": data["sample_size"],
                "note": f"{data['yes_count']} yes wins out of {data['total']} trades",
            })
    
    return rules


# =============================================================================
# MAIN
# =============================================================================

def run_analysis(min_samples: int = 10) -> Dict:
    """Run full pattern analysis on recorder data."""
    records = load_records()
    
    if not records:
        logger.warning("⚠️ No data available for analysis!")
        return {
            "status": "NO_DATA",
            "note": "Recorder data file is empty or missing. Run recorder.py to collect data.",
            "pct_above_50": {},
            "first_10_minutes": {},
            "price_trajectory": {},
            "by_coin": {},
            "trading_rules": [],
        }
    
    # Run all analyses
    pct_above_50 = analyze_pct_above_50_patterns(records, min_samples)
    first_10_min = analyze_first_N_minutes(records, minutes=10)
    trajectory = analyze_price_trajectory(records)
    by_coin = analyze_by_coin(records)
    
    # Generate trading rules
    trading_rules = generate_trading_rules({"pct_above_50": pct_above_50})
    
    return {
        "status": "OK",
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "total_records": len(records),
        "records_with_results": sum(1 for r in records if r.get("result") is not None),
        "pct_above_50": pct_above_50,
        "first_10_minutes": first_10_min,
        "price_trajectory": trajectory,
        "by_coin": by_coin,
        "trading_rules": trading_rules,
    }


def print_report(analysis: Dict):
    """Pretty-print the analysis report."""
    print("\n" + "=" * 70)
    print("🔍 RECORDER PATTERN ANALYSIS REPORT")
    print("=" * 70)
    
    if analysis["status"] == "NO_DATA":
        print("\n⚠️  NO DATA AVAILABLE")
        print(f"   {analysis.get('note', 'Unknown issue')}")
        print("\n   💡 To collect data:")
        print("   1. Run: cd /home/ubuntu/.openclaw/workspace/workers/recorder")
        print("   2. Run: python recorder.py")
        print("   3. Wait for markets to close and resolve")
        print("   4. Re-run this analysis")
        print("=" * 70)
        return
    
    print(f"\n📊 Analyzed at: {analysis['analyzed_at']}")
    print(f"📈 Total records: {analysis['total_records']}")
    print(f"✅ Records with results: {analysis['records_with_results']}")
    
    # Trading Rules (most important!)
    print("\n" + "-" * 70)
    print("🎯 TRADING RULES (Generated from historical data)")
    print("-" * 70)
    
    rules = analysis.get("trading_rules", [])
    if not rules:
        print("   Not enough data to generate rules yet.")
    else:
        for rule in rules:
            edge_str = f"+{rule['edge']:.1%}" if rule['edge'] > 0 else f"{rule['edge']:.1%}"
            print(f"   📌 IF {rule['condition']}")
            print(f"      THEN {rule['action']} (confidence: {rule['confidence']:.1%}, edge: {edge_str})")
            print(f"      Note: {rule.get('note', '')}")
            print()
    
    # Pct Above 50 Buckets
    pct = analysis.get("pct_above_50", {})
    buckets = pct.get("buckets", {})
    
    print("\n" + "-" * 70)
    print("📊 PCT_ABOVE_50 → WIN_RATE (Tony's Key Insight)")
    print("-" * 70)
    print("   When price above $0.50 for X% of time → YES resolves Y% of time")
    print()
    print("   Bucket      | Win Rate | Wins | Losses | Total | Edge vs 50%")
    print("   " + "-" * 60)
    
    for bucket_range, data in sorted(buckets.items()):
        wr = data["win_rate"]
        edge = wr - 0.5
        edge_str = f"+{edge:.1%}" if edge > 0 else f"{edge:.1%}"
        print(f"   {bucket_range:12} | {wr:7.1%}  | {data['yes_count']:4} | {data['no_count']:6} | {data['total']:5} | {edge_str}")
    
    # By Coin
    by_coin = analysis.get("by_coin", {}).get("by_coin", {})
    if by_coin:
        print("\n" + "-" * 70)
        print("🪙 WIN RATE BY COIN")
        print("-" * 70)
        print("   Coin   | Win Rate | YES | NO  | Total | Avg %>50")
        print("   " + "-" * 55)
        for coin, data in sorted(by_coin.items()):
            print(f"   {coin:6} | {data['win_rate']:7.1%} | {data['yes_count']:3} | {data['no_count']:4} | {data['total']:5} | {data['avg_pct_above_50']:.1%}")
    
    # Trajectories
    traj = analysis.get("price_trajectory", {}).get("trajectories", {})
    if traj:
        print("\n" + "-" * 70)
        print("📈 PRICE TRAJECTORY PATTERNS")
        print("-" * 70)
        print("   Trajectory    | Win Rate | YES | NO  | Total")
        print("   " + "-" * 45)
        for traj_name, data in sorted(traj.items()):
            print(f"   {traj_name:13} | {data['win_rate']:7.1%} | {data['yes_count']:3} | {data['no_count']:4} | {data['total']:5}")
    
    print("\n" + "=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Recorder Pattern Analyzer")
    parser.add_argument(
        "--min-samples",
        type=int,
        default=10,
        help="Minimum samples per bucket to include (default: 10)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON instead of human-readable",
    )
    args = parser.parse_args()
    
    analysis = run_analysis(min_samples=args.min_samples)
    
    if args.json:
        print(json.dumps(analysis, indent=2))
    else:
        print_report(analysis)


if __name__ == "__main__":
    main()
