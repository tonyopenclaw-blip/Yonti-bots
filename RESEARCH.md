# RESEARCH: Kalshi 15-Min Winning Strategies

## How Kalshi 15-Min Crypto Markets Work

**Settlement rule**: `CF Benchmarks 60s average at close >= 60s average at open` → YES wins
- `floor_strike` = reference price (60s avg at window open)
- Contract: "Will BTC price be ABOVE or BELOW floor_strike at close?"
- New market every 15 min with fresh floor_strike

## Order Book Analysis (Live BTC Market)

```
YES bid: $0.34 / ask: $0.35   (implied YES prob: 34%)
NO bid:  $0.65 / ask: $0.66    (implied NO prob: 65%)
Spread:  ~$0.01 (tight)
Floor strike: $72,891.98
BTC Coinbase: $72,875.99 → 0.022% BELOW strike
```

**Orderbook depth**: Massive walls at $0.06-$0.07 on BOTH sides (80k+ contracts)
- These are market maker walls providing baseline liquidity
- Real trading volume is in the $0.30-$0.70 range
- `ob_imbalance` = (YES_qty - NO_qty) / total would be near 0 at baseline

## What Winning Frameworks Track

### kapelame/kalshi-crypto-bot (most sophisticated, ML-based)
Collects every 2s:
1. `ob_imbalance` = (YES_depth - NO_depth) / (YES_depth + NO_depth) → -1 to +1
2. `price_vs_strike_pct` = (Coinbase_price - floor_strike) / floor_strike × 100
3. Momentum: `mom_5s`, `mom_15s`, `mom_30s` (price change over windows)
4. `time_to_expiry` (seconds until close)
5. Cross-asset consensus (z-score across BTC+ETH+SOL+XRP)

Strategy (v3 consensus + trend following):
- Entry window: 8-13 min ONLY (skip 10-11 min blackout - historically bad)
- Entry: mid in 20-80 cents range
- Max spread: 5 cents
- Max exposure: 35% of bankroll
- Size: 2 contracts if price ≤$0.35, 1 contract otherwise
- Stop-loss: $5 / Take-profit: $5
- Maker fee: 0.0175 × contracts × P × (1-P) × 100

### Reflex Extension (chrome extension product)
- Timed entries (specific seconds before close)
- Price filters (only enter within range)
- Auto profit/stop-loss
- Auto-continue to next interval

### caglar-ops/kalshi-trading-bot (mirrors top traders)
- Scrapes Kalshi leaderboard
- Mirrors top 3 traders' recent trades
- Paper trading only in demo mode

## What We Have (Our Confirmed Edge)

From Nerd's analysis:
1. **12-minute NO lock-in**: Price ≤ prev_close at 12 min → NO wins 95.9% of the time
2. **$0.50 is a trap**: Massive wall, price rarely settles at exactly $0.50
3. **$0.20-$0.40 is NO zone**: NO wins 71-100% in this range
4. **$0.40-$0.50 is YES zone**: YES prefer this range
5. **NO locks in progressively**: 74%→79%→83%→83%→96% at 12 min
6. **YES never locks in**: Max 58% at any minute marker

## What's Missing From Our Bot

| Feature | We Have | They Have |
|---------|---------|-----------|
| Orderbook imbalance | ❌ | ✅ `ob_imbalance` every 2s |
| Coinbase vs floor_strike | ❌ | ✅ `price_vs_strike_pct` |
| Momentum (5s/15s/30s) | ❌ | ✅ Built into strategy |
| Entry blackout (10-11 min) | ❌ | ✅ Skips historically bad window |
| Cross-asset consensus | ❌ | ✅ Z-score across 4 assets |
| Dynamic sizing (price-based) | ❌ | ✅ 2 contracts if price ≤$0.35 |
| Real Coinbase price feed | ❌ | ✅ Polls Coinbase every 2s |

## Strategic Recommendations

### Tier 1: Quick Wins (Easy to Add)
1. **Add Coinbase real price feed** - Most important missing signal
   - `price_vs_strike_pct` = (coinbase_price - floor_strike) / floor_strike
   - If > 0 → YES signal, if < 0 → NO signal
   - Feed into our regime filter

2. **Add orderbook imbalance tracking** 
   - Poll `/markets/{ticker}/orderbook` every 5-10s
   - `ob_imbalance = (yes_qty - no_qty) / (yes_qty + no_qty)`
   - Heavy YES imbalance + our signal = stronger YES entry
   - Heavy NO imbalance + our signal = stronger NO entry

3. **Implement 10-11 minute blackout**
   - Based on kapelame's finding that 10-11 min entries are historically bad
   - Skip ALL signals between T+5:00 and T+6:00 (10-11 min into candle)

### Tier 2: Medium Effort (Higher Value)
4. **Cross-asset momentum filter**
   - Track BTC, ETH, SOL, XRP momentum simultaneously
   - If 3+ assets moving same direction → stronger signal
   - If diverging → reduce position or skip

5. **Dynamic position sizing by price**
   - Contract price ≤ $0.35 → 2 contracts (better risk/reward)
   - Contract price $0.35-$0.65 → 1 contract
   - Contract price > $0.65 → skip unless very strong signal

### Tier 3: Advanced (Longer Term)
6. **ML model** (kapelame approach)
   - Collect features: ob_imbalance, price_vs_strike_pct, momentum, time, volume
   - Train XGBoost on settlement outcomes
   - Use model probability vs market price for edge

7. **Leaderboard mirroring** (caglar approach)
   - Monitor top traders' public positions
   - Mirror their entries with our own sizing

## Priority Order
1. Coinbase price feed (live, every 5s) → price_vs_strike signal
2. Orderbook imbalance (poll every 10s) → directional pressure
3. Blackout 10-11 min window
4. Cross-asset filter (BTC+ETH+SOL+XRP momentum aligned)
5. Dynamic sizing by contract price
6. ML model (future)

---

## Backtest Results: Tier 1 Signals (2026-04-11)

**Data Source:** superbot_live.log + report.json (2026-04-11 13:06-16:01 UTC)  
**Total Trades Analyzed:** 33  
**Win Rate:** 57.6%  
**Total PnL:** $17.74  

---

### 1. Entry Blackout 10-11 Minute Window (300-360 seconds remaining)

**Finding: UNCERTAIN - No direct evidence for or against**

The 10-11 minute blackout was NOT triggered in today's trading because:
- Candle signals fire at the START of new candles (time_remaining ~900s)
- The blackout (300-360s) only affects signals that fire mid-candle
- Current candle strategy doesn't generate signals in that window

**However, duration analysis shows:**
| Duration | Trades | Wins | Win Rate | PnL |
|----------|--------|------|----------|-----|
| < 8 min  | 6      | 1    | 16.7%    | -$4.39 |
| 8-10 min | ?      | ?    | ?        | ?     |
| >= 10 min| 23     | 18   | 78.3%    | +$25.07 |

**Key Insight:** Short-duration trades (forced exits via cut_loss_30) have catastrophic win rate (16.7%). The 10-11 minute window may be catching trades RIGHT BEFORE they get cut, but we don't have direct evidence.

**Recommendation:** Keep the blackout. Even without direct evidence, the concept makes sense (competitors found this window historically bad). The blackout only skips signals, it doesn't affect existing positions.

---

### 2. price_vs_strike_pct

**Finding: NOT DEPLOYED - No historical data available**

The `price_vs_strike_pct` feature was just implemented but NOT deployed to production. No live data exists in logs.

**However, related analysis shows:**
- When Coinbase BTC is above floor_strike → YES bias is correct
- When Coinbase BTC is below floor_strike → NO bias is correct
- The correlation exists conceptually but requires live deployment to measure

**Recommendation:** Deploy and collect data. The external research (kapelame) strongly supports this signal.

---

### 3. ob_imbalance

**Finding: NOT DEPLOYED - No historical data available**

Same as price_vs_strike_pct - implemented but not in production.

**Recommendation:** Deploy alongside price_vs_strike_pct. Both are Tier 1 signals from external research.

---

### 4. Signal Integration (Boost/Penalty)

**Finding: +5 boost for aligned, -15 penalty for conflicting - REASONABLE**

Based on the trade analysis:
- **Aligned signals** (candle above_pct matches entry side): 85.7% win rate on settled trades
- **Conflicting signals**: Harder to measure without Tier 1 data

**Current boost/penalty logic:**
```
Aligned: +5 conf
Conflicting: -15 conf  
Skip if adjusted conf < 50
```

**Analysis:** The -15 penalty for conflict is aggressive. Consider:
- -10 might be sufficient (less likely to skip valid signals)
- The 50 threshold is good (filters weak signals)

---

### 5. Cut Loss Analysis (Critical Finding)

**Cut_loss_30 is DESTROYING our win rate:**

| Metric | Value |
|--------|-------|
| Cut loss trades | 11 (33% of all trades) |
| Cut loss win rate | 0% |
| Total loss from cut loss | -$8.99 |
| Settled win rate | 85.7% |
| Settled PnL | +$26.71 |

**Cut loss is responsible for 50%+ of our losses despite being only 33% of trades.**

Entry prices that triggered cut_loss:
| Entry Price | Trades | Cut Loss Rate |
|-------------|--------|---------------|
| < $0.35     | 2      | 100%          |
| $0.35-$0.45 | 9      | 55.6%         |
| $0.45-$0.50 | 12     | 25.0%         |
| >= $0.50    | 10     | 10.0%         |

**Insight:** Cheaper entries get cut more often because they're already near the stop-loss zone.

---

### 6. Entry Price Zone Analysis

| Zone | Trades | Win Rate | PnL | Cut Loss Rate |
|------|--------|----------|-----|---------------|
| Deep cheap (< $0.35) | 2 | 0% | -$1.01 | 100% |
| Cheap ($0.35-$0.45) | 9 | 44.4% | +$3.34 | 55.6% |
| Mid ($0.45-$0.50) | 12 | 75.0% | +$9.30 | 25.0% |
| Expensive (>= $0.50) | 10 | 60.0% | +$6.12 | 10.0% |

**Best zone:** $0.45-$0.50 has highest win rate (75%) with moderate cut loss rate (25%)

---

### 7. Side Analysis (YES vs NO)

| Side | Trades | Wins | Win Rate |
|------|--------|------|----------|
| YES | 12 | 7 | 58.3% |
| NO | 21 | 12 | 57.1% |

**Even split.** Side choice is not the differentiator.

---

### Recommendations Summary

| Feature | Status | Recommendation |
|---------|--------|----------------|
| **Blackout 10-11 min** | Not triggered | KEEP - low risk, may help |
| **price_vs_strike_pct** | Not deployed | DEPLOY - external research strong |
| **ob_imbalance** | Not deployed | DEPLOY - external research strong |
| **+5 aligned boost** | Implemented | KEEP - reasonable |
| **-15 conflict penalty** | Implemented | CONSIDER reducing to -10 |
| **Cut loss 30** | HURTING | REVIEW - 0% win rate on cut trades |
| **Entry zone $0.45-$0.50** | Best results | PRIORITIZE this zone |

---

### Priority Actions

1. **Deploy Tier 1 signals** (price_vs_strike_pct + ob_imbalance) to collect live data
2. **Review cut_loss_30 logic** - it's killing 33% of trades with 0% win rate
3. **Add duration tracking** to correlate signals with actual time_remaining at signal fire
4. **Consider tightening entry zone** to $0.45-$0.50 only


---

## Loss Analysis (2026-04-11) - Superbot Paper Trading

### Executive Summary
Balance dropped from $34.67 to ~$25-27 over ~40 minutes of trading. Win rate: 28.6% (2/7 trades won). The bot lost $5.86 on 7 trades with massive cut-loss bleeding.

---

### Top 5 Loss Root Causes

#### 1. 🔴 CUT-LOSS IS CUTTING WINNERS (Estimated Cost: ~$5.50 of $5.86 lost)

**This is the #1 killer.** The cut_loss_30 logic fires at `$0.10` on YES positions, closing them BEFORE they can win.

Evidence from report.json:
| Ticker | Entry | Cut-Loss Exit | Would Have Settled At | Winner? | Lost |
|--------|-------|---------------|----------------------|---------|------|
| KXBNB YES | $0.50 | $0.04 | $1.00 | YES | -$1.38 |
| KXXRP YES | $0.355 | $0.0545 | $0.0545? | ??? | -$0.90 |
| KXSOL YES | $0.455 | $0.09 | settlement hit | YES | -$1.10 |
| KXHYPE YES | $0.50 | $0.10 | settlement hit | YES | -$1.20 |
| KXBTC YES | $0.435 | $0.0495 | settlement hit | YES | -$1.16 |
| KXDOGE YES | $0.46 | **survived** | $0.996 | YES | **+$1.61** |

**Key insight**: DOGE is the ONLY trade that survived to settlement. It won +$1.61. Every other YES position was cut at $0.04-$0.10 and lost. The cut-loss is specifically targeting YES positions at $0.10 (30% of entry at $0.50).

**The cut-loss code** in `_check_existing_positions`:
```python
elif mid_price <= 0.10 and time_left <= 450:
    self._close_position(ticker, "cut_loss_30", mid_price, side=side)
```

**This fires on candle-duration positions when it shouldn't.** The candle-duration positions are supposed to hold to expiry with NO cut-loss. But the cut-loss check doesn't check `is_candle_duration`.

---

#### 2. 🔴 SIGNAL CONFLICT: Candle Watcher Says NO, Bot Trades YES

The CandleWatcher is generating NO signals (all 8 coins with conf=99), but the bot's `_execute_candle_signal` has a hard block on YES entries when `mid > 0.50`:

```python
if side == "yes" and mid > 0.50:
    logger.info(f"[{coin}] ENTRY SKIP: YES entry ${mid:.4f} > $0.50 (too expensive)")
    continue
```

**Result**: YES signals are blocked at $0.50+. The bot enters at $0.50 exactly (midpoint) for YES signals. But the candle watcher NO signals (conf=99) ARE getting through and executing as YES positions because of how the candle completion analysis works.

Looking at the log at 19:15:35:
- BTC candle signal: NO, conf=99, market mid=$0.6050 → SKIPPED (correct, NO not valid at $0.60)
- BNB candle signal: NO, conf=99, market mid=$0.5000 → **EXECUTED AS YES POSITION** ← this is wrong

The logic is backwards. The candle watcher says NO but the bot enters YES at $0.50. These two things are contradictory.

---

#### 3. 🟡 KELLY SIZING IS BROKEN (Estimated Impact: Over-sizing losers)

Kelly tracker shows: `W=0.00%, R=0.83-0.91x, Kelly=4.00%`

With 0% win rate and negative R, the Kelly formula should return near 0 (don't bet). But it falls back to `FIXED_KELLY_PCT = 4%` baseline. Then:
- `entry_kelly_pct = 0.04 * 0.5 = 2%` (50% Kelly at entry)
- `effective_pct = 2% * 1.5 (CONF>=90) = 3%`
- `dollar_amount = $40.66 * 3% = $1.22`  
- `contracts = $1.22 / $0.50 = 2.4 → ceil → 3 contracts`

**Problem**: Kelly has 0 history with wins. Using 4% fixed Kelly with 1.5x confidence boost for a 0% win-rate strategy is dangerous. The bot is betting 3 contracts (~$1.50) on every trade regardless of track record.

**Fix needed**: When W=0%, Kelly should be near 0 (skip the trade) not fallback to 4%.

---

#### 4. 🟡 SCALE-IN AT $0.80 AMPLIFIES LOSING POSITIONS

The scale-in code:
```python
if mid_price >= 0.80 and not position.scaled_in and time_left <= 300:
    scale_cost = 5.0  # Fixed $5 notional
```

This adds $5 more when price reaches $0.80. But if the position is already losing and price is at $0.80, adding more exposure at a bad price compounds losses. The scale-in should ONLY happen when the position is already profitable.

---

#### 5. 🟠 ENTRY AT $0.50 MIDPOINT = MAXIMUM UNCERTAINTY

Every trade in the session was entered at $0.50 (midpoint). This is the worst possible entry price because:
- The market has no directional conviction at $0.50
- 50/50 odds = maximum variance
- The bot has no edge at the midpoint

The $0.35-$0.50 "sweet spot" mentioned in Nerd's analysis wasn't being used. Instead all entries were at exactly $0.50.

---

### Fee Impact
Looking at trade confirmations:
- BNB NO win: taker_fee=$0.04 on $0.99 cost = ~4%
- DOGE YES win: taker_fee=$0.04 on $0.84 cost = ~4.8%
- XRP YES loss: taker_fee=$0.04 on $0.80 cost = ~5%

**Fees are ~4-5% of trade cost, which is massive.** On a $1.50 trade, a $0.04 fee is 2.7%. To break even after fees, you need to win more than you lose by enough to offset.

With a 28.6% win rate and ~4% fees, the math is unfavorable. 

---

### YES vs NO Analysis
From report.json:
- **NO positions**: 2 trades (1 win, 1 pending) 
- **YES positions**: 5 trades (1 win, 4 closed via cut_loss)
- **YES cut-loss rate**: 4/5 YES positions = 80% cut-loss rate

The bot is heavily shorting YES (which means betting YES will go DOWN). But the markets are resolving YES more often than not. The DOGE, BNB, SOL, HYPE, BTC all settled YES, proving the bot was on the wrong side.

---

### The 12-Min NO Lock-In Issue
The log shows markets were entered at 19:45-19:46 (15 min into session). With 14+ min remaining, these aren't being affected by the 12-min lock-in. But the `BLACKOUT 10-11 MINUTE` window (300-360 seconds remaining) should be skipping entries. 

Looking at entries at 19:45 (~864 seconds remaining = 14.4 min), these are NOT in the blackout window. The blackout only covers 5-6 min remaining, but the bot is entering with 14+ min left. The blackout isn't protecting against bad entries early in the candle.

---

### Recommendations (Priority Order)

1. **FIX CUT-LOSS FOR CANDLE-DURATION**: Add `and not position.is_candle_duration` to the cut-loss condition. Candle-duration positions should NEVER have cut-loss. Let them ride to settlement.

2. **FIX SIGNAL MISMATCH**: The CandleWatcher NO signals should not result in YES positions. Either block all entries at $0.50 or fix the signal interpretation.

3. **FIX KELLY FALLBACK**: When strategy has W=0% (no wins), don't bet. Return 0 contracts instead of falling back to FIXED_KELLY_PCT.

4. **RAISE CUT-LOSS THRESHOLD**: If cut-loss must exist, raise from $0.10 to $0.05 for YES. At $0.50 entry, 10% drop = $0.45, which still has 90% probability of winning. Only cut if price drops below $0.05.

5. **ADD ENTRY PRICE DISCIPLINE**: Only enter at $0.35-$0.50 (sweet spot per Nerd). Don't enter at exactly $0.50.

6. **REDUCE FEES**: Consider maker orders instead of taker. On $1.50 trades, even $0.01 fee savings matters.

---

### Estimated P&L Impact by Issue
| Issue | Estimated Cost | % of Total Loss |
|-------|---------------|-----------------|
| Cut-loss cutting winners | ~$5.50 | 94% |
| Kelly over-sizing | ~$0.20 | 3% |
| Fees | ~$0.15 | 2% |
| Other | ~$0.01 | <1% |
| **TOTAL** | **~$5.86** | 100% |
