#!/usr/bin/env python3
"""
Hourly Analyzer - Superbot Learning System
Runs hourly, analyzes signal_log.json for patterns, posts findings to Discord webhook.
"""
import json
import os
import sys
import time
import requests
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).parent
SIGNAL_LOG = BASE_DIR / "signal_log.json"
DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1492688796938932267/O1rP8V0V0QntVzLV9HE8hT8Bew-4GofQStjz7Kd2FLZ_h0N5ntaKR_ehGzIeNQzeBDFC"

def load_log():
    if not SIGNAL_LOG.exists():
        return []
    with open(SIGNAL_LOG) as f:
        return json.load(f)

def analyze():
    log = load_log()
    if not log:
        return None

    now = datetime.utcnow()
    cutoff = (now - timedelta(hours=24)).isoformat()

    # Filter to last 24h
    recent = [e for e in log if e.get('timestamp', '') >= cutoff]

    # Settled signals
    taken = [e for e in recent if e.get('action') == 'TAKEN' and e.get('settlement_result') is not None]
    blocked = [e for e in recent if e.get('action') == 'BLOCKED' and e.get('settlement_result') is not None]

    # Win rate for TAKEN
    taken_wins = sum(1 for e in taken if e.get('won') == True)
    taken_losses = sum(1 for e in taken if e.get('won') == False)
    taken_total = taken_wins + taken_losses
    taken_wr = (taken_wins / taken_total * 100) if taken_total > 0 else 0

    # Win rate for BLOCKED (would-have-won)
    blocked_ww = sum(1 for e in blocked if e.get('won') == True)
    blocked_wl = sum(1 for e in blocked if e.get('won') == False)
    blocked_total = blocked_ww + blocked_wl
    blocked_wr = (blocked_ww / blocked_total * 100) if blocked_total > 0 else 0

    # STEALTH_TIER1 analysis
    stealth = [e for e in recent if e.get('signal_type') == 'STEALTH_TIER1']
    stealth_taken = [e for e in stealth if e.get('action') == 'TAKEN' and e.get('settlement_result') is not None]
    stealth_wins = sum(1 for e in stealth_taken if e.get('won') == True)
    stealth_losses = sum(1 for e in stealth_taken if e.get('won') == False)
    stealth_total = stealth_wins + stealth_losses
    stealth_wr = (stealth_wins / stealth_total * 100) if stealth_total > 0 else 0

    # Coin breakdown for TAKEN
    coin_stats = {}
    for e in taken:
        coin = e.get('coin', 'UNK')
        if coin not in coin_stats:
            coin_stats[coin] = {'wins': 0, 'losses': 0}
        if e.get('won') == True:
            coin_stats[coin]['wins'] += 1
        elif e.get('won') == False:
            coin_stats[coin]['losses'] += 1

    # Side breakdown
    yes_taken = [e for e in taken if e.get('side') == 'YES']
    no_taken = [e for e in taken if e.get('side') == 'NO']
    yes_wr = sum(1 for e in yes_taken if e.get('won')) / len(yes_taken) * 100 if yes_taken else 0
    no_wr = sum(1 for e in no_taken if e.get('won')) / len(no_taken) * 100 if no_taken else 0

    # Findings
    findings = []
    if stealth_total > 0:
        findings.append(f"STEALTH_TIER1: {stealth_total} fired, {stealth_wr:.0f}% WR ({stealth_wins}W/{stealth_losses}L)")
    if taken_total >= 5:
        findings.append(f"TAKEN: {taken_total} trades, {taken_wr:.0f}% WR ({taken_wins}W/{taken_losses}L)")
        findings.append(f"YES: {len(yes_taken)} trades, {yes_wr:.0f}% WR | NO: {len(no_taken)} trades, {no_wr:.0f}% WR")
    if blocked_total > 0:
        findings.append(f"BLOCKED: {blocked_total} settled, {blocked_ww} would-have-won ({blocked_wr:.0f}% WR)")

    # Top coins
    if coin_stats:
        sorted_coins = sorted(coin_stats.items(), key=lambda x: x[1]['wins']/(x[1]['wins']+x[1]['losses']+0.01), reverse=True)
        top = [f"{c}: {(s['wins']/(s['wins']+s['losses'])*100):.0f}%" for c, s in sorted_coins[:3] if (s['wins']+s['losses']) >= 2]
        if top:
            findings.append(f"Top coins: {', '.join(top)}")

    if not findings:
        return None

    msg = (
        f"📊 **HOURLY ANALYSIS** `{now.strftime('%H:%M UTC')}`\n"
        f"{'—'*30}\n"
    )
    for f in findings:
        msg += f"• {f}\n"

    msg += f"{'—'*30}\n"
    msg += f"_Analyzing {len(recent)} recent signals_"

    return msg

if __name__ == '__main__':
    result = analyze()
    if result:
        print(result)
        try:
            requests.post(DISCORD_WEBHOOK, json={"content": result}, timeout=10)
            print("Posted to Discord.")
        except Exception as e:
            print(f"Discord error: {e}")
    else:
        print("No significant data to report.")
