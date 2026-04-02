#!/bin/bash
WEBHOOK_URL="https://discord.com/api/webhooks/1486066262122430684/mLKWVlGJRyADWEnpDgx3n4QcI1B-JhAnDLyBHKwsK-BSmeo5lal5MYrrY_QiuOBqiNLy"

REPORT="🍝 **UNCLE VITO'S BETTING REPORT** 🍝
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📅 04/02/2026 | **24** games | 3-Leg Parlays

🏀 **NBA**

  Props (3-Leg):
  1. LaMelo Ball (CHA) - **OVER** points 23.5
  2. Miles Bridges (CHA) - **OVER** rebounds 5.5
  3. Kevin Durant (PHX) - **OVER** points 26.5
  📈 Odds: **+595** | 🎯 68%

  Spread/Total/ML (3-Leg):
  1. CHA vs PHX - **CHA** (-1.5)
  2. MIN vs DET - **MIN** O/U 240.5
  3. LAL vs OKC - **LAL** ML
  📈 Odds: **+738** | 🎯 68%

🧊 **NHL**

  Props (3-Leg):
  1. Brady Tkachuk (OTT) - **OVER** points 0.5
  2. Tage Thompson (BUF) - **UNDER** goals 0.5
  3. Sidney Crosby (PIT) - **UNDER** points 1.5
  📈 Odds: **+595** | 🎯 68%

  Spread/Total/ML (3-Leg):
  1. OTT vs BUF - **OTT** (-1.5)
  2. TB vs PIT - **TB** O/U 7.0
  3. FLA vs BOS - **FLA** ML
  📈 Odds: **+524** | 🎯 68%

⚾ **MLB**

  Props (3-Leg):
  1. Bobby Witt Jr. (KC) - **OVER** hits 0.5
  2. Carlos Correa (MIN) - **UNDER** hits 0.5
  3. Vladimir Guerrero Jr. (TOR) - **UNDER** RBI 0.5
  📈 Odds: **+595** | 🎯 68%

  Spread/Total/ML (3-Leg):
  1. KC vs MIN - **KC** (-1.5)
  2. ARI vs ATL - **ARI** O/U 10.0
  3. NYM vs SF - **NYM** ML
  📈 Odds: **+774** | 🎯 68%

🌐 **CONFIDENCE PARLAY** (all leagues)

1. 🏀 LaMelo Ball - **OVER** points 23.5 (68%)
2. 🏀 Miles Bridges - **OVER** rebounds 5.5 (68%)
3. 🏀 Kevin Durant - **OVER** points 26.5 (68%)
4. 🏀 CHA - **CHA** (-1.5) (68%)
5. 🏀 MIN - **MIN** O/U 240.5 (68%)

🌐 Odds: **+2435** | 🎯 **68%** confidence | 5 legs

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️ _Do your own homework. Uncle Vito don't miss._"

PAYLOAD=$(printf '{"content": %s}' "$(echo "$REPORT" | jq -Rs .)")
curl -s -H "Content-Type: application/json" \
    -d "$PAYLOAD" \
    "$WEBHOOK_URL"
echo ""
echo "Done"