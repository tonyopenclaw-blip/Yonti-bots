#!/usr/bin/env python3
"""
Superbot Nerd Analysis - Monitors Superbot performance every 15 minutes
Compares trades against Nerd's documented best practices, posts insights to Discord.
"""

import json
import os
import sys
from datetime import datetime, timedelta
from collections import defaultdict

REPORT_PATH = "/home/ubuntu/.openclaw/workspace/workers/superbot/report.json"
RESEARCH_PATH = "/home/ubuntu/.openclaw/workspace/workers/nerd/research.md"
OUTPUT_FILE = "/home/ubuntu/.openclaw/workspace/workers/superbot_nerd/last_analysis.txt"
WEBHOOK_URL = "https://discord.com/api/webhooks/1486066262122430684/mLKWVlGJRyADWEnpDgx3n4QcI1B-JhAnDLyBHKwsK-BSmeo5lal5MYrrY_QiuOBqiNLy"

# Nerd's documented zones
ZONES = {
    "deep_buy": {"min": 0.05, "max": 0.15, "strategy": "deep_buy"},
    "drift_buy": {"min": 0.35, "max": 0.45, "strategy": "drift_buy"},
    "dead_zone": {"min": 0.45, "max": 0.55, "strategy": "dead_zone"},
    "drift_short": {"min": 0.55, "max": 0.65, "strategy": "drift_short"},
    "snipe_short": {"min": 0.75, "max": 0.95, "strategy": "snipe_short"},
}

STATS = {
    "drift_buy": {"wins": 0, "losses": 0, "total_pnl": 0, "entries": []},
    "drift_short": {"wins": 0, "losses": 0, "total_pnl": 0, "entries": []},
    "deep_buy": {"wins": 0, "losses": 0, "total_pnl": 0, "entries": []},
    "deep_short": {"wins": 0, "losses": 0, "total_pnl": 0, "entries": []},
}


def load_trades():
    if not os.path.exists(REPORT_PATH):
        return []
    with open(REPORT_PATH) as f:
        data = json.load(f)
    return data.get("trades", [])


def classify_entry(entry_price, strategy):
    """Check if entry was in the correct zone per Nerd's research."""
    if strategy == "drift_buy":
        if 0.35 <= entry_price <= 0.45:
            return "correct_zone"
        elif 0.45 < entry_price < 0.55:
            return "dead_zone"
        elif entry_price < 0.35:
            return "below_zone"
        else:
            return "above_zone"
    elif strategy == "drift_short":
        if 0.55 <= entry_price <= 0.65:
            return "correct_zone"
        elif 0.45 <= entry_price < 0.55:
            return "dead_zone"
        elif entry_price > 0.65:
            return "above_zone"
        else:
            return "below_zone"
    elif strategy == "deep_buy":
        if entry_price <= 0.15:
            return "correct_zone"
        elif entry_price <= 0.35:
            return "drift_buy_zone"
        else:
            return "above_zone"
    return "unknown"


def analyze_trades(trades):
    results = {
        "total": len(trades),
        "by_strategy": defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0, "entries": []}),
        "zone_analysis": defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0, "entries": []}),
        "recent_trades": [],
        "session_stats": {}
    }

    # Load session stats from report
    if os.path.exists(REPORT_PATH):
        with open(REPORT_PATH) as f:
            data = json.load(f)
            results["session_stats"] = {
                "start_time": data.get("start_time", ""),
                "balance": data.get("ending_balance", 0),
                "pnl": data.get("total_pnl", 0),
                "win_rate": data.get("win_rate", 0),
                "total_trades": data.get("total_trades", 0),
                "open_positions": data.get("open_positions", 0),
            }

    for t in trades:
        strat = t.get("strategy", "unknown")
        entry = t.get("entry_price", 0)
        pnl = t.get("pnl", 0)
        is_win = pnl > 0
        is_open = t.get("exit_reason", "") == "" or not t.get("close_time")

        zone_result = classify_entry(entry, strat)
        results["zone_analysis"][zone_result]["pnl"] += pnl
        results["zone_analysis"][zone_result]["entries"].append({
            "entry": entry,
            "pnl": pnl,
            "strategy": strat
        })
        if is_win:
            results["zone_analysis"][zone_result]["wins"] += 1
        else:
            results["zone_analysis"][zone_result]["losses"] += 1

        results["by_strategy"][strat]["pnl"] += pnl
        results["by_strategy"][strat]["entries"].append(entry)
        if is_win:
            results["by_strategy"][strat]["wins"] += 1
        else:
            results["by_strategy"][strat]["losses"] += 1

        # Recent trades (last 5)
        if len(results["recent_trades"]) < 5:
            results["recent_trades"].append({
                "ticker": t.get("ticker", ""),
                "strategy": strat,
                "entry": entry,
                "pnl": pnl,
                "is_win": is_win,
                "exit_reason": t.get("exit_reason", "OPEN"),
                "side": t.get("side", "")
            })

    return results


def generate_insights(results):
    insights = []
    lines = []

    stats = results.get("session_stats", {})
    pnl = stats.get("pnl", 0)
    wr = stats.get("win_rate", 0)
    balance = stats.get("balance", 0)

    lines.append("🧠 **SUPERBOT NERD ANALYSIS** 🧠")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # Session summary
    pnl_emoji = "📈" if pnl >= 0 else "📉"
    lines.append(f"{pnl_emoji} Session P&L: {'+' if pnl >= 0 else ''}${pnl:.2f} | WR: {wr:.1f}% | Balance: ${balance:.2f}")
    lines.append("")

    # Zone analysis
    zone = results.get("zone_analysis", {})
    correct = zone.get("correct_zone", {"wins": 0, "losses": 0, "pnl": 0})
    dead = zone.get("dead_zone", {"wins": 0, "losses": 0, "pnl": 0})

    if correct["wins"] + correct["losses"] > 0:
        correct_wr = correct["wins"] / (correct["wins"] + correct["losses"]) * 100
        lines.append(f"✅ **Correct Zone Trades:** {correct['wins']}W/{correct['losses']}L ({correct_wr:.0f}%) | P&L: {'+' if correct['pnl'] >= 0 else ''}${correct['pnl']:.2f}")

    if dead["wins"] + dead["losses"] > 0:
        dead_wr = dead["wins"] / (dead["wins"] + dead["losses"]) * 100 if (dead["wins"] + dead["losses"]) > 0 else 0
        lines.append(f"⚠️ **Dead Zone Trades:** {dead['wins']}W/{dead['losses']}L ({dead_wr:.0f}%) | P&L: {'+' if dead['pnl'] >= 0 else ''}${dead['pnl']:.2f}")
        if dead["losses"] > dead["wins"]:
            lines.append("   → **Avoid trading $0.45–$0.55** (per Nerd's research)")

    # Strategy breakdown
    by_strat = results.get("by_strategy", {})
    for strat in ["drift_buy", "drift_short", "deep_buy", "deep_short"]:
        if strat not in by_strat:
            continue
        s = by_strat[strat]
        total = s["wins"] + s["losses"]
        if total == 0:
            continue
        wr_s = s["wins"] / total * 100
        wr_emoji = "✅" if wr_s >= 55 else "⚠️" if wr_s >= 45 else "❌"
        lines.append(f"{wr_emoji} **{strat}:** {s['wins']}W/{s['losses']}L ({wr_s:.0f}%) | {'+' if s['pnl'] >= 0 else ''}${s['pnl']:.2f}")

        # Check entry zone compliance
        if strat == "drift_buy":
            in_zone = sum(1 for e in s["entries"] if 0.35 <= e <= 0.45)
            out_zone = total - in_zone
            if out_zone > 0:
                lines.append(f"   → {out_zone}/{total} entries OUTSIDE $0.35–$0.45 zone")
        elif strat == "drift_short":
            in_zone = sum(1 for e in s["entries"] if 0.55 <= e <= 0.65)
            out_zone = total - in_zone
            if out_zone > 0:
                lines.append(f"   → {out_zone}/{total} entries OUTSIDE $0.55–$0.65 zone")

    lines.append("")

    # Recent trades
    recent = results.get("recent_trades", [])
    if recent:
        lines.append("📋 **Last 5 Trades:**")
        for t in recent:
            pnl_str = f"+${t['pnl']:.2f}" if t['pnl'] >= 0 else f"-${abs(t['pnl']):.2f}"
            win_str = "✅" if t["is_win"] else "❌"
            lines.append(f"  {win_str} {t['ticker'][-10:]} | {t['strategy']} | E:${t['entry']:.2f} | {pnl_str} | {t['exit_reason'][:30]}")

    # Actionable recommendations
    lines.append("")
    lines.append("🎯 **Recommendations:**")

    # Check for patterns
    drift_buy = by_strat.get("drift_buy", {"wins": 0, "losses": 0})
    drift_short = by_strat.get("drift_short", {"wins": 0, "losses": 0})

    recommendations = []

    if drift_buy["wins"] + drift_buy["losses"] > 3:
        db_wr = drift_buy["wins"] / (drift_buy["wins"] + drift_buy["losses"]) * 100
        if db_wr < 40:
            recommendations.append("drift_buy win rate low — check entries are in $0.35–$0.45 zone only")

    if drift_short["wins"] + drift_short["losses"] > 3:
        ds_wr = drift_short["wins"] / (drift_short["wins"] + drift_short["losses"]) * 100
        if ds_wr < 40:
            recommendations.append("drift_short win rate low — verify entries at $0.55–$0.65")

    if dead["losses"] > 2:
        recommendations.append("stop trading dead zone ($0.45–$0.55) — go/no-go only")

    if pnl < -10:
        recommendations.append("session P&L deeply negative — consider pausing")

    if not recommendations:
        recommendations.append("no critical issues detected — continue monitoring")

    for r in recommendations:
        lines.append(f"  → {r}")

    return "\n".join(lines)


def post_to_discord(message):
    import subprocess
    import json as json_lib

    payload = json_lib.dumps({"content": message})
    result = subprocess.run(
        ["curl", "-s", "-X", "POST", "-H", "Content-Type: application/json",
         "-d", payload, WEBHOOK_URL],
        capture_output=True, text=True
    )
    return result.returncode == 0


def main():
    trades = load_trades()
    if not trades:
        print("No trades found in report.json")
        return

    results = analyze_trades(trades)
    report = generate_insights(results)

    print(report)

    # Save last analysis
    with open(OUTPUT_FILE, "w") as f:
        f.write(report)

    # Check if content changed
    changed = True
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE) as f:
            last = f.read()
        changed = (report != last)

    if changed:
        print("\n📤 Posting to Discord...")
        post_to_discord(report)
    else:
        print("\n⏭️ No change, skipping Discord post.")


def check_first_cross_ready():
    """Check if First Cross Tracker has 30+ records, notify Tony if ready."""
    import json as json_lib
    
    cross_path = "/home/ubuntu/.openclaw/workspace/workers/superbot/target_cross_data.json"
    flag_path = "/home/ubuntu/.openclaw/workspace/workers/superbot_nerd/first_cross_ready.txt"
    
    if not os.path.exists(cross_path):
        return
    
    try:
        with open(cross_path) as f:
            data = json_lib.load(f)
        count = len(data)
        
        # Already notified?
        if os.path.exists(flag_path):
            return
        
        if count >= 30:
            msg = "🎯 **First Cross Data Ready!**\n"
            msg += f"{count} markets accumulated. Nerd ready to analyze.\n"
            msg += "@tbruno94 - ready when you are sir."
            post_to_discord(msg)
            with open(flag_path, "w") as f:
                f.write(str(count))
            print(f"\n🔔 Notified Tony: {count} first cross records ready!")
    except Exception as e:
        print(f"First cross check error: {e}")


if __name__ == "__main__":
    check_first_cross_ready()
    main()
