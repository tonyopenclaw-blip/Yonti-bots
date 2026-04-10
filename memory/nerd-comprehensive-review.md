# Nerd's Comprehensive Strategy Review
**Date:** 2026-04-10 04:00 UTC  
**Purpose:** Everything we've learned + actionable plan for Tony  

---

## 1. What's Actually Working RIGHT NOW

### Current Session (03:46 UTC, 8 minutes old)
The bot just restarted and has 3 open positions — all LOSING:

| Position | Entry | Current | Loss |
|----------|-------|---------|------|
| BTC yes (momentum, CONF=65) | $0.505 | $0.095 | **-81%** |
| ETH yes (candle-duration, CONF=95) | $0.675 | $0.295 | **-56%** |
| DOGE yes (candle-duration, CONF=95) | $0.715 | $0.550 | **-23%** |

All 3 fired within 1 minute of startup. The candle-duration signals were 100% above open (max confidence) but immediately reversed. **No closed trades yet in this session** — it's too early to judge.

### Historical Context (from nerd analyses)
The current session losses don't disprove the candle-duration signal — they reveal a **live-vs-historical mismatch**:

- **Historical candle-duration (>80% above open):** 80-99% win rate measured from candle OPEN to candle CLOSE
- **Live implementation:** Tracks current price vs open in real-time — a fundamentally different signal
- The 3 candle-duration entries this morning were at 100% above open at entry time, but the candles REVERSED before expiry

**This is the #1 problem to fix.**

---

## 2. The Candle-Duration Signal — Real Assessment

### What We Know (from nerd-ending-matrix.md)
- **>80% above open → BUY YES:** 90-99% historical bullish rate (ETH: 98.8%, BTC: 96.3%, SOL: 98.7%)
- **<20% above open → BUY NO:** 96-98% historical bearish rate
- **40-60% zone → NO TRADE** (neutral, ~50/50)

### The Problem: Live vs Historical Mismatch
The historical analysis measured: *"Did price spend X% of the candle's LIFETIME above the previous close, and did the candle close higher?"*

The live bot measures: *"Is price currently X% above the candle's open right now?"*

These are NOT the same signal. The historical analysis had the full candle to play out. The live bot is entering mid-candle when price happens to be elevated — and then the candle can reverse before expiry.

**Evidence:** ETH was at $0.675 (100% above open) at entry. Settled at $0.295. The "100% above open" was a fakeout.

### Should We ONLY Use Candle-Duration?
**Not yet.** The signal needs to be fixed first. Right now it's broken because of the live-vs-historical mismatch.

**What needs to change:**
1. Use the signal ONLY at the candle OPEN (or within first 2 minutes), not mid-candle
2. Require >90% above open (tighten from 80%)
3. Require entry price ≤ $0.85 (avoid buying at extreme froth)
4. Let it ride to EXPIRY — no take-profit, no stop-loss

---

## 3. What to STOP Doing

### 🚫 Midpoint Crosses (first_cross at ~$0.50)
**Kill it.** Data shows:
- These coins are essentially random walks at 15-min resolution
- Entry at $0.50 with momentum thesis = paying fair value for a binary that reverts
- The April 9 session lost -$21.83 with 30 trades mostly from first_cross entries
- Win rate: 40%, R ratio: 0.71x → **mathematically guaranteed to lose**

### 🚫 Momentum at Midpoint ($0.45-$0.55)
**Kill it.** Momentum persistence is absent in 7/8 coins. Only BNB/HYPE/ADA show marginal momentum at 2-4 min windows — not exploitable through Kalshi's 15-min binaries.

### 🚫 Scale-ins at Midpoint
**Kill it.** Every scale-in this morning was into a losing position. Scale-ins only make sense when you have a high-confidence directional thesis. At $0.50, you don't.

### 🚫 Stop-Loss at $0.30 on Candle-Duration Entries
**Stop using SL on candle-duration trades.** The signal works over the full candle lifecycle. A $0.30 stop cuts winners before the pattern completes. Let candle-duration trades ride to expiry.

### 🚫 The 401 Balance Spam
**Fix it.** The bot is hitting balance 401s every 30 seconds, exhausting auth tokens, and using stale balance for sizing. It's not blocking trades, but it's corrupting position sizing. **Quick fix:** Cache balance for 5 minutes, only refresh on trade execution.

---

## 4. What to START Doing

### ✅ Pure Candle-Duration with Fixed Rules

**Revised signal logic:**
```
IF price is above previous candle's close for >90% of the current candle's 
elapsed time (not just current position vs open)
AND entry price ≤ $0.85
AND coin is ETH or SOL (strongest historical pattern)
THEN BUY YES, ride to expiry, no SL, no TP
```

**Key insight from ending-matrix:**
> The signal predicts whether the CANDLE will close higher. It needs the full candle. Mid-candle entries at elevated prices get chopped.

### ✅ Only CONF 90+ Entries
Current: taking CONF 65 momentum signals. 
Fix: Only take candle-duration at CONF 90+, ignore everything else.

### ✅ Coin Ranking for Candle-Duration

| Rank | Coin | >80% above prev_close → Bullish | Notes |
|------|------|--------------------------------|-------|
| 1 | ETH | 98.8% | Best edge, strongest signal |
| 2 | SOL | 98.7% | Nearly as good as ETH |
| 3 | BTC | 96.3% | Clean, reliable |
| 4 | DOGE | 92.3% | Good, but noisier |
| 5 | XRP | 96.5% | Good |
| 6 | ADA | 92.1% | Also strong at <20% bucket |
| 7 | BNB | 93.9% | Slightly weaker |
| 8 | HYPE | 90.6% | Weakest of the good coins |

**Prefer: ETH > SOL > BTC > XRP > DOGE > ADA**

### ✅ Better Exit Rules
For candle-duration YES entries:
- **No take-profit** — the signal is "close higher," don't second-guess it
- **No stop-loss** — let it ride to the 15-min expiry
- **Exception:** If you MUST exit early, only exit if price drops below the candle's OPEN price (i.e., the signal invalidated itself)

### ✅ Wait for New Candle Cycle
Entry timing matters. The candle-duration signal works best at:
- **Candle open (T+0):** Perfect — you know the previous candle's stats
- **First 2 minutes:** Acceptable — candle still has 13+ min to play out
- **Minutes 3-15:** Risky — you're betting on momentum that may already be exhausted

---

## 5. Best Coin for Candle-Duration

**Winner: ETH** (98.8% bullish rate when >80% above prev_close)
- Strongest edge of any coin at any bucket
- 81 historical occurrences with 80 of them bullish
- Also shows best mean-reversion behavior on the downside (P(Up→Up T+1) = 0.447)

**Runner-up: SOL** (98.7% bullish rate, 79/80 occurrences)
- Nearly identical to ETH
- Slightly more volatile = bigger swings

**Practical recommendation:** Run ETH and SOL candle-duration only. Everything else is secondary.

---

## 6. What Pixel Needs to Build

### v3 Superbot: Candle-Duration Only

```
STRATEGY: candle_duration_only
COINS: ETH, SOL (only)
ENTRY: 
  - At candle open, check if prev candle: prev_close_above_open_pct > 90%
  - OR during candle: price has been above prev_close for >90% of elapsed time
  - AND entry_price <= 0.85
  - AND confidence >= 90
ENTRY PRICE FILTERS:
  - Reject any entry > $0.85 (too frothy, likely to reverse)
  - Reject any entry < $0.20 (already too close to floor)
EXIT:
  - Hold until expiry (15 min)
  - No SL, no TP
  - Exception: If price drops below candle OPEN, close immediately
KELLY: 4% (keep same)
MAX POSITIONS: 3 (keep same)
CANDLE_GRANULARITY: 15-min Coinbase
POLLING: Coinbase every 10s (keep), Kalshi every 30s (keep)
```

### Fix 401 Balance Issue
```
- Cache balance on startup and after each trade
- Only re-fetch balance every 5 minutes OR on trade execution
- On 401: use cached balance, do NOT spam retry
```

---

## 7. Summary: The Plan

### KEEP
- Candle-duration signal (it's our ONLY edge)
- ETH, SOL as primary coins
- 4% Kelly sizing
- Coinbase pre-filter (free market data)
- 30s Kalshi polling

### STOP
- first_cross at $0.50 (losing thesis)
- Momentum signals at midpoint (no edge)
- Scale-ins (losing strategy)
- SL/TP on candle-duration trades
- CONF 65 entries (too weak)
- All coins simultaneously (spreads capital thin)

### CHANGE
- Candle-duration: tighten to >90% threshold, ≤$0.85 entry max
- Entry timing: only at candle open or first 2 minutes
- Exit: hold to expiry, no early exits
- Balance refresh: cache for 5 min, stop 401 spam

### ADD
- New "candle_duration_only" strategy mode in superbot
- Per-coin win rate tracking (measure actual performance)
- Session P&L tracking that persists across restarts

---

## 8. The Hard Truth

We've spent 4 analyses proving what DOESN'T work:
- RSI: doesn't work (32-35% win rate)
- MACD: doesn't work (28-47% win rate)  
- Moving averages: doesn't work (31-35% win rate)
- Mean-reversion at extremes: theoretically correct but hard to time
- Momentum at midpoint: doesn't work (40% win rate, 0.71x R)

The candle-duration signal is the ONLY thing with a real edge (90-99% historical win rate). But it's been implemented incorrectly (mid-candle entries vs. full-candle analysis).

**Fix the implementation. Then test. Then we know.**

If candle-duration works correctly: we have a profitable strategy.
If it doesn't: we have no edge and should stop trading.

---

*Analysis by Nerd | 2026-04-10 04:00 UTC*
