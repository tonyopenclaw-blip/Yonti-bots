#!/usr/bin/env python3
"""
analyze_signals.py - Analyze signal outcomes to evaluate blocking decisions.

Reads signal_log.json and reports:
- Total signals by type
- Taken vs Blocked breakdown
- Win rate for TAKEN signals
- Win rate for BLOCKED signals (what would have happened if we took them)
- Net P&L analysis

Usage: python analyze_signals.py
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional


def load_signal_log() -> List[Dict]:
    """Load signal log from JSON file."""
    log_file = Path(__file__).parent / "signal_log.json"
    if not log_file.exists():
        print("❌ signal_log.json not found")
        return []
    try:
        with open(log_file, "r") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        print("❌ Error decoding signal_log.json")
        return []


def analyze_signals(signals: List[Dict]) -> Dict:
    """Analyze signals and compute statistics."""
    if not signals:
        return {"error": "No signals in log"}

    total = len(signals)
    taken = [s for s in signals if s.get("action") == "TAKEN"]
    blocked = [s for s in signals if s.get("action") == "BLOCKED"]
    pending = [s for s in signals if s.get("action") in (None, "PENDING")]
    settled = [s for s in signals if s.get("settlement_result") is not None]

    # Win rates for settled signals
    def win_rate(sig_list):
        if not sig_list:
            return None, 0
        won = [s for s in sig_list if s.get("won") is True]
        return len(won) / len(sig_list) * 100 if sig_list else 0, len(sig_list)

    taken_wr, taken_n = win_rate([s for s in taken if s.get("settlement_result") is not None])
    blocked_wr, blocked_n = win_rate([s for s in blocked if s.get("settlement_result") is not None])

    # By signal type breakdown
    by_type: Dict[str, Dict] = {}
    for s in signals:
        key = s.get("signal_type", "unknown")
        if key not in by_type:
            by_type[key] = {"total": 0, "taken": 0, "blocked": 0, "taken_wins": 0, "blocked_wins": 0}
        by_type[key]["total"] += 1
        if s.get("action") == "TAKEN":
            by_type[key]["taken"] += 1
            if s.get("won") is True:
                by_type[key]["taken_wins"] += 1
        elif s.get("action") == "BLOCKED":
            by_type[key]["blocked"] += 1
            if s.get("won") is True:
                by_type[key]["blocked_wins"] += 1

    # Block reasons breakdown
    block_reasons: Dict[str, int] = {}
    for s in blocked:
        reason = s.get("block_reason", "unknown")
        block_reasons[reason] = block_reasons.get(reason, 0) + 1

    return {
        "total": total,
        "taken": {"count": len(taken), "settled": len([s for s in taken if s.get("settlement_result") is not None]), "win_rate": taken_wr, "n": taken_n},
        "blocked": {"count": len(blocked), "settled": len([s for s in blocked if s.get("settlement_result") is not None]), "win_rate": blocked_wr, "n": blocked_n},
        "pending": len(pending),
        "settled": len(settled),
        "by_type": by_type,
        "block_reasons": block_reasons,
    }


def print_report(stats: Dict):
    """Print formatted analysis report."""
    print("\n" + "=" * 60)
    print("📊 SIGNAL OUTCOME ANALYSIS")
    print("=" * 60)

    if "error" in stats:
        print(f"❌ {stats['error']}")
        return

    print(f"\n📈 OVERVIEW")
    print(f"   Total signals:  {stats['total']}")
    print(f"   Settled:         {stats['settled']}")
    print(f"   Pending:         {stats['pending']}")

    taken = stats.get("taken", {})
    blocked = stats.get("blocked", {})

    print(f"\n🎯 TAKEN SIGNALS")
    print(f"   Count: {taken['count']}")
    if taken.get("n", 0) > 0:
        print(f"   Settled: {taken['n']}")
        print(f"   Win rate: {taken['win_rate']:.1f}%")
    else:
        print(f"   Settled: 0 (waiting for settlement)")

    print(f"\n🚫 BLOCKED SIGNALS")
    print(f"   Count: {blocked['count']}")
    if blocked.get("n", 0) > 0:
        print(f"   Settled: {blocked['n']}")
        print(f"   Win rate (if taken): {blocked['win_rate']:.1f}%")
        if blocked['win_rate'] > 50:
            print(f"   ⚠️  WARNING: Blocking winners! {blocked['win_rate']:.1f}% of blocked signals would have won.")
    else:
        print(f"   Settled: 0 (waiting for settlement)")

    # By signal type
    print(f"\n📋 BY SIGNAL TYPE")
    for sig_type, data in stats.get("by_type", {}).items():
        print(f"\n   {sig_type}:")
        print(f"     Total: {data['total']}")
        if data['taken'] > 0:
            wr = data['taken_wins'] / data['taken'] * 100 if data['taken'] > 0 else 0
            print(f"     Taken: {data['taken']} (win rate: {wr:.1f}%)")
        if data['blocked'] > 0:
            wr = data['blocked_wins'] / data['blocked'] * 100 if data['blocked'] > 0 else 0
            print(f"     Blocked: {data['blocked']} (win rate if taken: {wr:.1f}%)")

    # Block reasons
    if stats.get("block_reasons"):
        print(f"\n🚫 BLOCK REASONS")
        for reason, count in stats.get("block_reasons", {}).items():
            print(f"   {count}x: {reason}")

    print("\n" + "=" * 60)


def main():
    signals = load_signal_log()
    stats = analyze_signals(signals)
    print_report(stats)


if __name__ == "__main__":
    main()
