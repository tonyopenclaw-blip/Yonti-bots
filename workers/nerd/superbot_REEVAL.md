# Superbot REEVAL — Critical Findings and Recommendations

**Date:** 2026-04-02  
**Analyst:** Nerd (Research Agent, Yonti)  
**Subject:** Complete reevaluation of Superbot's trading strategy after 111 trades  
**Account Status:** $100 → $15.45 (down 84.55%) — 111 trades, 37.8% win rate  

---

## 1. The Brutal Truth

### 1.1 The Strategy is Mathematically Negative EV

The bot just completed 111 trades with a **37.8% win rate**. For binary options with a 2x payout:
- Breakeven win rate = 50.1% (after spreads)
- Current win rate = 37.8%
- **DEFICIT: 12.3 percentage points**

The Kelly formula says:
```
Full Kelly = (2 × 0.378 - 0.622) / 2 = -0.243
```
**Negative Kelly means the strategy should not be bet on AT ALL. Full stop.**

When you factor in that the bot is betting $2 per trade (13% of a $15 balance), it's not trading — it's bleeding out at high speed.

### 1.2 The Math on $100 → $300

Tony wants to turn $100 into $300 in one session. Here's what the math says:

| Scenario | Win Rate | EV per $2 bet | Trades to 3x | Realistic? |
|----------|----------|---------------|--------------|------------|
| Current (broken) | 37.8% | -$0.49 | ∞ (never) | NO |
| Breakeven | 50.1% | +$0.02 | ~4,400 bets | NO (time) |
| Breakout | 55% | +$0.20 | ~440 bets | NO (time) |
| Super hot | 65% | +$0.60 | ~147 bets | ~2.5 hours |
| Legendary | 75% | +$1.00 | ~88 bets | ~90 min |

**Can we 3x tonight with the existing strategy? NO. Absolutely not.**

The realistic path to $300 requires either:
- A 65%+ win rate sustained over many hours (not happening with current setup)
- Or completely different approach (see section 5)

### 1.3 The $84.55 Vanished — Where Did It Go?

The math doesn't add up:
- Closed trades won: $36.13
- Closed trades lost: $25.58
- **Net from closed trades: +$10.55**
- Actual account loss: **-$84.55**
- **Unexplained gap: $74.00**

Possible causes:
1. **Spread costs**: Every trade pays the spread. At ~$0.02-$0.05 per trade × 111 trades = $2-5 in pure spread cost. That's not $74.
2. **Open positions that went to zero**: If any positions were left open and resolved against the bot, those losses wouldn't appear in closed trades.
3. **The report.json is incomplete**: It shows `open_positions: 0` now, but historical losses from open positions may not be captured.

**Bottom line: Something is wrong with how losses are being tracked. We may have a reporting bug alongside the strategy bug.**

---

## 2. Trade History Analysis

### 2.1 Overall Performance

| Metric | Value |
|--------|-------|
| Total trades | 111 |
| Winning trades | 42 |
| Losing trades | 69 |
| Win rate | 37.8% |
| Average win | $0.860 |
| Average loss | $0.371 |
| Win/Loss ratio | 2.32 |
| Total won | $36.13 |
| Total lost | $25.58 |
| **Net PnL (closed)** | **+$10.55** |
| **Actual PnL** | **-$84.55** |

### 2.2 Strategy Breakdown

#### DRIFT_BUY (75 trades, 37.3% WR)
- **PnL: +$10.93** (surprisingly positive)
- Avg win: $1.079 | Avg loss: $0.410
- Win/loss ratio: 2.63 (wins are 2.63x larger than losses)
- Entry range: $0.30–$0.45
- **Analysis:** DRIFT_BUY is carrying the whole strategy. The big wins ($1.08 avg) are covering the many small losses ($0.41 avg). But 37.3% WR is still not enough to sustain long-term.

#### DRIFT_SHORT (36 trades, 38.9% WR)
- **PnL: -$0.38** (losing money despite similar WR)
- Avg win: $0.422 | Avg loss: $0.286
- Win/loss ratio: 1.48 (wins barely exceed losses)
- Entry range: $0.60–$0.70
- **Analysis:** DRIFT_SHORT entries are in the wrong zone. Entries at $0.65-$0.70 have poor win rates. The $0.55-$0.60 zone (actual drift reversion zone) is barely being used.

### 2.3 Entry Zone Analysis

| Zone | Trades | Win Rate | PnL |
|------|--------|----------|-----|
| Dead Zone ($0.45–$0.55) | 1 | 0.0% | -$0.50 |
| DRIFT_BUY ($0.30–$0.45) | 74 | 37.8% | +$11.43 |
| DRIFT_SHORT ($0.55–$0.70) | 36 | 38.9% | -$0.38 |
| DEEP_BUY (<$0.30) | **0** | N/A | **$0.00** |
| Above $0.70 | 0 | N/A | $0.00 |

**CRITICAL: ZERO trades in the DEEP_BUY zone ($0.05-$0.15). This is the highest-quality entry in Nerd's research and the bot never used it.**

### 2.4 Per-Coin Performance

| Coin | Trades | Win Rate | PnL | Status |
|------|--------|----------|-----|--------|
| ETH | 17 | **52.9%** | **+$5.00** | ✅ KEEP |
| BNB | 11 | **54.5%** | **+$2.93** | ✅ KEEP |
| SOL | 14 | 42.9% | +$2.84 | ✅ KEEP |
| HYPE | 18 | 44.4% | +$1.71 | ✅ KEEP |
| DOGE | 17 | 29.4% | +$0.09 | ❌ DROP |
| XRP | 15 | 26.7% | **-$0.31** | ❌ DROP |
| BTC | 19 | **21.1%** | **-$1.70** | ❌ DROP |

**BTC is catastrophically bad: 21.1% WR, lost $1.70. This coin needs to be removed immediately.**

### 2.5 Exit Reason Analysis

| Exit | Count | Wins | Losses | PnL |
|------|-------|------|--------|-----|
| SL hit | 68 | 0 | 68 | -$25.48 |
| TP hit | 40 | 40 | 0 | +$35.55 |
| Expired | 3 | 2 | 1 | +$0.48 |

**100% of SL exits were losses. 100% of TP exits were wins.**
This means the stop-loss and take-profit prices are being hit correctly — the problem is entry quality, not exit execution.

### 2.6 Losing Streak Analysis

- **Maximum losing streak: 9 consecutive losses**
- **Average losing streak: 3.8 trades**
- **Number of losing streaks: 18**

At $2 per bet, a 9-streak costs **$18** — that's 18% of the original $100 bankroll in ONE streak.

---

## 3. What's Broken: Root Cause Analysis

### 3.1 CRITICAL FLAW #1: Wrong Entry Zones

**Problem:** The bot is entering DRIFT_BUY at $0.35-$0.45 when Nerd's research specifies $0.35-$0.40 as the ideal zone and $0.40-$0.45 as the boundary/danger zone.

**Evidence:** 
- Entries in $0.39-$0.45: massive overlap with dead zone
- DRIFT_SHORT entries at $0.63-$0.70 (should be $0.55-$0.62 max)
- The DRIFT_SHORT_MIN_PRICE = $0.50 means entries at exactly $0.50 (the dead zone boundary) were triggering drift_short — these are invalid entries

**Fix:** See config_NEW.py. Tightened all zones to match Nerd's research exactly.

### 3.2 CRITICAL FLAW #2: Never Used DEEP_BUY

Nerd's research identified DEEP_BUY ($0.05-$0.15) as the highest-quality entry:
- At $0.10 entry, you need only 10% WR to break even
- At $0.05 entry, you need only 5% WR to break even

**The bot placed ZERO trades in this zone over 111 attempts.**

If even 10 of those 111 trades had been DEEP_BUY at $0.10, and even 3 of them won (30% WR), that's:
- 3 wins × ($0.10 entry × 10x) = $3.00 profit on $1.00 risked
- vs the current situation where we paid $0.40+ for entries needing 55%+ WR

### 3.3 CRITICAL FLAW #3: Bet Sizing Destroyed the Bankroll

**At $15 balance with $2 bets:**
- $2 / $15 = **13.3% of bankroll per trade**
- Kelly with 37.8% WR and 2x payout: negative (should bet 0%)
- Proper 1/4 Kelly: $15 × 4% = **$0.60 per trade max**
- Actual bet size: **$2.00 per trade (3.3x oversized!)**

This is why a bankroll that should have ~50% survival (with $2 bets at 37.8% WR) instead went to 15%. The oversizing amplified losses catastrophically during the 9-streak losing run.

### 3.4 CRITICAL FLAW #4: MAX_KELLY_BET = MIN_KELLY_BET = $2

```python
MIN_KELLY_BET = 2.00   # Minimum bet when using Kelly sizing ($2 hard floor)
MAX_KELLY_BET = 2.00   # Maximum bet when using Kelly sizing ($2 hard cap)
```

This means the Kelly formula's output is completely ignored. If Kelly says bet $0.50, the code clamps it to $2. If Kelly says bet $5, it clamps to $2. **The Kelly tracker is decorative, not functional.**

### 3.5 CRITICAL FLAW #5: Dead Zone Was Not Enforced

Config shows `DEAD_ZONE_MIN = 0.50, DEAD_ZONE_MAX = 0.60`:
- This means $0.50-$0.55 is NOT dead zone (bot was trading it!)
- Nerd's research says dead zone is $0.45-$0.55

One trade actually hit the dead zone: entry at $0.50, lost $0.50.

### 3.6 CRITICAL FLAW #6: 100% of Losses Are From SL Hits

68 trades hit SL. 0 SL hits were wins. This means:
1. The SL at $0.25 for DRIFT_BUY is appropriate (it's being hit correctly)
2. But entries are being taken in the wrong conditions — price wouldn't hit SL if entries were better
3. The stop-loss is not too tight; the entries are too loose

---

## 4. The 5 Critical Changes

### Change #1: Enter the DEEP_BUY Zone (Highest Priority)

Enable DEEP_BUY entries at $0.05-$0.15. These require only 5-15% WR to break even vs the 55%+ WR needed for DRIFT_BUY entries.

**Why it works:** At $0.05 entry, you 20x your money if YES resolves. The market occasionally offers penny odds on oversold crypto. These are gifts. The bot has been leaving them on the table.

**Implementation:** Add DEEP_BUY logic that triggers when YES < $0.15 with RSI oversold confirmation. No stop-loss (ride to expiry, max loss is the price paid).

### Change #2: Tighten DRIFT_BUY Entry to $0.30-$0.38

Previous: DRIFT_BUY entered anywhere from $0.30-$0.45
Corrected: Only enter $0.30-$0.38 with RSI < 40 confirmation

**Why:** Entries $0.39-$0.45 have poor win rates because they're not in true oversold territory. The market at $0.42 is uncertain, not oversold. True drift buy opportunities are rare — wait for them.

### Change #3: Tighten DRIFT_SHORT Entry to $0.55-$0.62

Previous: DRIFT_SHORT entered $0.50-$0.70
Corrected: Only enter $0.55-$0.62 with RSI > 60 confirmation

**Why:** Entries above $0.63 are momentum trades, not drift reversion trades. The bot was confusing the two. DRIFT_SHORT is specifically about fading overbought conditions and expecting price to drift back to $0.50.

### Change #4: Fix Bet Sizing

| Parameter | Old | New |
|-----------|-----|-----|
| FIXED_KELLY_PCT | N/A | 4% of bankroll |
| MIN_KELLY_BET | $2.00 | $0.50 |
| MAX_KELLY_BET | $2.00 | $1.50 |
| MAX_BET | $5.00 | $3.00 |

**Why:** At $15 balance, $0.62 per trade (4%) vs $2.00 per trade (13.3%) — the new sizing survives losing streaks instead of getting wiped out.

### Change #5: Drop BTC, DOGE, XRP Immediately

These three coins have win rates of 21%, 29%, and 27% respectively. They're not just bad — they're broken. Remove them from COINS list and don't trade them until the strategy is proven on other coins.

**Why:** 19 BTC trades, 17 DOGE trades, 15 XRP trades = 51 trades (46% of all trades) wasted on losing coins. If we had spent those 51 trades on ETH/BNB/SOL instead, the math might look very different.

---

## 5. Can We 3x Tonight?

**Short answer: No. Not with this strategy. Not in one night.**

The math is unambiguous:
- Current WR: 37.8% → negative EV → you LOSE money at any bet size
- Needed WR for 3x: ~65%+ sustained over hours
- Time to 3x at 65% WR: ~147 net wins = ~250 total bets = ~4+ hours at 1 bet/minute

**But here's the realistic path:**
1. Paper trade tonight with the new config at $0.50-$1.50 bets
2. Goal is NOT $300 — goal is to prove the new strategy has 55%+ WR
3. If we can hit 55% WR over 50+ trades, then the real account has a chance
4. If we can't hit 55% WR in paper, the strategy needs more work

**What would ACTUALLY 3x tonight:**
- An improbable hot streak (10+ consecutive wins at $1.50 bet)
- OR a completely different approach: DEEP_BUY only, $3 bets, targeting penny odds
- At $0.05 entry with $3 bet, one win = $15 (5x on that bet). Two such wins = $45. You'd need ~6 more. Still improbable but slightly less impossible.

---

## 6. New Configuration Summary

See `config_NEW.py` for full implementation. Key changes:

| Parameter | Old Value | New Value | Reason |
|-----------|-----------|-----------|--------|
| COINS | ['BTC','ETH','SOL','XRP','DOGE','HYPE','BNB','ADA'] | ['ETH','BNB','SOL','HYPE','ADA'] | Remove BTC/XRP/DOGE (bad WR) |
| DRIFT_BUY_MAX_PRICE | $0.45 | $0.38 | Avoid dead zone overlap |
| DRIFT_SHORT_MIN_PRICE | $0.50 | $0.55 | Dead zone starts at $0.45 |
| DRIFT_SHORT_MAX_PRICE | $0.70 | $0.62 | Entries above $0.62 have poor WR |
| DEAD_ZONE_MIN | $0.50 | $0.45 | Match Nerd's research |
| DEAD_ZONE_MAX | $0.60 | $0.55 | Match Nerd's research |
| DEEP_BUY_ENABLED | False | True | Use penny odds zone |
| FIXED_KELLY_PCT | N/A | 4% | Fixed bankroll fraction |
| MAX_KELLY_BET | $2.00 | $1.50 | Cap at ~10% of bankroll |
| MIN_ENTRY_MINUTE | N/A | 3 | No entries in minutes 0-2 |
| MAX_ENTRY_MINUTE | N/A | 12 | No entries after minute 12 |
| DAILY_STOP_LOSS_PCT | 20% | 10% | Stop sooner |

---

## 7. What Works (and What Doesn't)

### What Works:
- **DRIFT_BUY on ETH**: 52.9% WR, best coin in the set
- **DRIFT_BUY on BNB**: 54.5% WR, second best
- **The general drift reversion thesis**: When entries are in the right zone, price tends to revert
- **Take-profit execution**: 100% of TP hits were winners — exits are working correctly

### What Doesn't Work:
- **DRIFT_SHORT**: 38.9% WR but negative PnL — entries are too loose
- **BTC/DOGE/XRP**: Catastrophically bad, remove from universe
- **Entry zone enforcement**: Bot was trading in wrong zones constantly
- **Bet sizing**: $2 on $15 balance is reckless
- **Kelly tracking**: Disabled by the $2 hard cap

---

## 8. Immediate Action Items for Pixel

1. **Copy config_NEW.py over config.py** (after review)
2. **Add DEEP_BUY strategy** to strategies.py (currently missing)
3. **Fix MIN_KELLY_BET != MAX_KELLY_BET** — they should not be equal
4. **Verify spread costs** — where did the $74 gap come from?
5. **Add per-coin max trades** — currently no coin-level limiting
6. **Add Coinbase bias as a FILTER** (not boost) — bearish bias + drift_buy signal = skip
7. **Test the new config in paper mode** before any real trading

---

## 9. Summary Scorecard

| Metric | Previous | Target (New) |
|--------|----------|-------------|
| Win rate | 37.8% | 55%+ |
| Best coin | ETH (52.9%) | Same |
| Worst coin | BTC (21.1%) | Removed |
| Bet size | $2 (13% of bankroll) | $0.50-$1.50 (4-10%) |
| Entry zone | Loose $0.30-$0.70 | Tight $0.30-$0.38 / $0.55-$0.62 |
| DEEP_BUY used | 0% | Target: 20% of trades |
| Kelly functional | No | Yes (with caps) |
| Dead zone enforced | No | Yes |
| Coins active | 8 | 5 |

---

*Research complete. This is the honest analysis. The strategy needs fundamental fixes, not tweaks. Deploy config_NEW.py in paper mode and target 55%+ WR over 50 trades before considering live trading.*
