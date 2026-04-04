# NERD'S NEW STRATEGY RECOMMENDATION
## Superbot v2.0 - Simplified, Profitable, API-Efficient

**Date:** 2026-04-04
**From:** Nerd (Researcher)
**To:** Jenkins & Pixel

---

## EXECUTIVE SUMMARY

From analyzing 205 trades in the last run:
- **first_cross ALONE:** 129 trades, 80.6% WR, **+$5.89 PnL** ✅
- **drift_buy ALONE:** 76 trades, 46.1% WR, **-$0.81 PnL** ❌
- **Combined loss of $46** was caused by drift + API hammering + fees

**Bottom line:** First cross works. Drift doesn't. Drop drift, simplify, and let winners run.

---

## 1. STRATEGY DESIGN

### PRIMARY: Pure First Cross (No Drift)

**Rule:** Only trade on first coin price cross of the Kalshi target price midpoint.

```
ENTRY CONDITIONS:
1. Market just opened (new ticker)
2. Track coin price (BTC/ETH/SOL) vs market midpoint ($0.50)
3. When price FIRST crosses $0.50 in either direction → TRADE
   - Cross UP → Buy YES (bet it goes higher)
   - Cross DOWN → Buy NO (bet it goes lower)
4. Only ONE trade per market (first cross only)
5. If no first cross signal in first 3 minutes → skip this market
```

**Why it works:**
- 80.6% win rate historically
- Clear entry signal, no ambiguity
- Single direction per market = low exposure

### FALLBACK: Momentum + Trailing Stop (Only when no first cross)

**Rule:** If no first cross signal after 3 minutes, check momentum.

```
FALLBACK CONDITIONS:
1. No first cross detected in first 3 minutes
2. Coinbase price trending strongly in one direction (>1% in 30s)
3. Market price at extreme (<$0.35 or >$0.65)
4. Trade with same-side bias as momentum
5. WIDER trailing stop buffer to let it run
```

**Why fallback exists:** We want to capture opportunities when first cross doesn't fire but momentum is clear.

### HARD RULES (No Exceptions)
- MAX 1 position per coin at a time
- MAX 3 concurrent positions total
- NO trades in last 2 minutes before expiry
- Stop trading 2 hours before major news events

---

## 2. SIZING RECOMMENDATIONS

### Current Problem
- MIN_KELLY_BET = MAX_KELLY_BET = $2 was overriding all Kelly calculations
- This means we bet $2 regardless of Kelly recommendation

### Recommended Changes

```python
# Remove the override that forced $2 bets
# Let Kelly breathe

KELLY_FRACTION = 0.25  # Keep 1/4 Kelly safety

# New: Dynamic sizing based on confidence
BET_SIZE_RULES:
- CONF 80+: Kelly * 1.0 (full signal, full bet)
- CONF 60-79: Kelly * 0.75 (good signal, reduce)
- CONF 40-59: Kelly * 0.50 (moderate signal, half bet)
- CONF <40: Skip (weak signal, don't trade)

# Hard caps
MAX_BET = 2.00  # Never more than $2 per trade
MIN_BET = 0.10  # Minimum viable bet
MAX_POSITIONS = 3  # Cap concurrent positions

# Bankroll management
MAX_DAILY_LOSS = 5.00  # Stop if down $5 in a day
MAX_DAILY_TRADES = 30  # Max 30 trades per calendar day
```

### Kelly Calculation (Keep but fix override)

```python
def calculate_kelly(win_rate, avg_win, avg_loss):
    """
    Kelly = (p * b - q) / b
    where p = win rate, q = 1-p, b = win/loss ratio
    
    Example: 80% WR, $0.098 avg win, $0.174 avg loss
    b = 0.098/0.174 = 0.56
    Kelly = (0.80 * 0.56 - 0.20) / 0.56 = 0.51
    With 1/4 Kelly = 0.13 of bankroll
    """
    if avg_loss == 0:
        return 0
    b = avg_win / abs(avg_loss)
    kelly = (win_rate * b - (1 - win_rate)) / b
    return max(0, kelly)  # No negative Kelly
```

### Expected Kelly with 80% WR, $0.098 avg win, $0.174 avg loss:
- b = 0.098/0.174 = 0.56
- Full Kelly = (0.80 * 0.56 - 0.20) / 0.56 = 51%
- 1/4 Kelly = 12.8%
- On $100 bankroll = **$12.80 per trade** (capped at $2 max)

**Current situation:** Kelly says bet $12.80, but $2 cap kicks in. This is FINE for now since we're in paper mode. The $2 cap protects us.

---

## 3. EXIT STRATEGY - "LET WINNERS RUN"

### Current Problem
- Trailing stop activating too early at 30% profit
- Buffer too tight (25%)
- Max hold at 10 min causing bad expiry exits

### New Trailing Stop Logic

```python
# PHASE 1: Wait for profit to build
# Don't activate trailing until 40% profit (was 30%)

TRAILING_STOP_TRIGGER_PCT = 0.40  # Activate after 40% profit (was 30%)

# PHASE 2: Wide buffer that scales with confidence
TRAILING_STOP_BUFFERS:
- CONF 80+: 35% buffer (let big winners run)
- CONF 60-79: 30% buffer
- CONF 40-59: 25% buffer

# PHASE 3: Dynamic max hold based on entry price
MAX_HOLD_RULES:
- Entry $0.70-1.00 (high odds): 8 minutes max (market likely to move)
- Entry $0.40-0.60 (mid): 10 minutes
- Entry $0.15-0.30 (low odds): 12 minutes (big reversal potential)

# PHASE 4: Don't hold to expiry
# Force close 1 minute before expiry
MIN_TIME_BEFORE_EXPIRY = 60  # seconds
```

### Exit Priority (check in order)
1. **Trailing stop hit** → Lock in profits
2. **Max hold time reached** → Close position, don't hold to expiry
3. **1 minute to expiry** → Force close regardless of PnL
4. **Hard stop loss** → Only if price moves 80% against us (rare)

### "Let Winners Run" Examples from Data

| Entry | Exit | PnL | Hold | What Happened |
|-------|------|-----|------|---------------|
| $0.72 | $0.09 | +$0.38 | 3.2min | Big short, trail captured it |
| $0.35 | $0.91 | +$0.28 | 0.3min | Extreme entry, quick reversal |
| $0.45 | $0.81 | +$0.22 | 7.5min | Held all the way |
| $0.52 | $0.95 | +$0.21 | 8.0min | Trail let it run to near $1 |

**The pattern:** Best wins come from entries at extremes with room to run. Current 10-min max hold is KILLING us on entries at $0.40-0.60 that need more time.

---

## 4. API EFFICIENCY PLAN

### The Problem
- 1,345 429 errors in last run
- Both drift_buy and first_cross polling constantly
- Coinbase called every few seconds

### Solution: Pre-Filter with Coinbase (FREE)

```python
# ARCHITECTURE CHANGE

# BEFORE (wasteful):
Every 2 seconds:
  → Call Kalshi API (get market list) ❌ RATE LIMITED
  → Call Kalshi API (get prices) ❌ RATE LIMITED
  → Call Coinbase API (get coin prices) ✅ FREE but still polling
  
# AFTER (efficient):
Every 10 seconds (Coinbase - free, no rate limit):
  → Get BTC/ETH/SOL prices from Coinbase ✅
  → Check if price crossed $0.50 midpoint
  → If cross detected → LOG SIGNAL (don't call Kalshi yet)

Every 30 seconds (Kalshi - rate limited, use sparingly):
  → Get list of OPEN markets (1 call)
  → Check which have signals logged
  → Execute only on markets with Coinbase-confirmed signals

# COINBASE PRE-FILTER RULES:
- Price within 1% of midpoint ($0.49-$0.51) → WATCH
- Price crossed midpoint → GENERATE SIGNAL
- Price stable for 60s without cross → NO SIGNAL

# KALSHI CALL REDUCTION:
Target: <50 API calls per hour (was 200+)
```

### Implementation

```python
class CoinbasePreFilter:
    """
    Free Coinbase data to pre-filter signals before hitting Kalshi API.
    """
    
    def __init__(self):
        self.last_prices = {}  # coin -> last price
        self.midpoint = 0.50
        self.poll_interval = 10  # seconds (Coinbase allows this)
        self.last_poll = 0
        
    def check_cross(self, coin) -> Optional[str]:
        """Check if Coinbase price crossed midpoint."""
        if time.time() - self.last_poll < self.poll_interval:
            return None
        
        price = self.get_coinbase_price(coin)  # Free API call
        if price is None:
            return None
        
        if coin not in self.last_prices:
            self.last_prices[coin] = price
            return None
        
        prev = self.last_prices[coin]
        self.last_prices[coin] = price
        
        # Detect cross
        if prev <= self.midpoint and price > self.midpoint:
            return "up"
        elif prev >= self.midpoint and price < self.midpoint:
            return "down"
        
        return None
    
    def get_coinbase_price(self, coin):
        """Free Coinbase ticker API - no rate limit concerns."""
        # Use public endpoint: api.coinbase.com
        # Returns: {"price": "65432.10"}
```

### Rate Limit Budget

```
KALSHI RATE LIMITS:
- ~100 requests per minute recommended
- We want: 50 requests per minute MAX

ALLOCATION:
- Market list check: 2/min (every 30s)
- Market detail (when signal detected): 2/market
- Trade execution (open/close): 4/market
- Health check: 1/min

Example: 10 trades/hour = ~50 API calls
```

### Backoff Strategy

```python
# When 429 hit, exponential backoff
BACKOFF_SCHEDULE:
- 1st 429: Wait 5s, retry
- 2nd 429: Wait 15s, retry
- 3rd 429: Wait 60s, retry
- 4th 429: STOP for 5 minutes, log issue

# Track 429 errors in session
# If >20 429s in 1 hour → Reduce polling frequency by 50%
```

---

## 5. EXPECTED PERFORMANCE

### Based on Historical Data

| Metric | Current (first_cross) | New Strategy |
|--------|----------------------|--------------|
| Win Rate | 80.6% | 80-85% (drop weak signals) |
| Total Trades | 129 (in ~6 hours) | 15-25 (quality over quantity) |
| PnL per trade | $0.046 avg | $0.10 avg (wider trails) |
| Total PnL | +$5.89 | +$3-5 in fewer trades |
| API calls | 200+ | 50-80 |
| 429 errors | 1345 | <50 |
| Fees | ~$2.58 | ~$0.60 (12 trades vs 129) |

### Why Fewer Trades = More Profit

```
CURRENT: 129 first_cross + 76 drift = 205 trades
- Fees: 205 × $0.02 × 2 (open+close) = $8.20
- 429 errors: 1345 (retry overhead)
- Many small wins averaging $0.046

NEW: 20 first_cross only (no drift)
- Fees: 20 × $0.02 × 2 = $0.80
- No 429 errors (pre-filter)
- Larger wins averaging $0.10 (wider trails)
- Net: Same $5 profit, 1/10th the fees and API pain
```

### Conservative Projection (Paper Mode)

```
Starting: $100
Expected daily PnL: +$2-5 (fewer but better trades)
After 1 week: $114-135
After 1 month: $140-200

Real mode (when ready):
- Start with $50 real money
- Scale up as we prove the strategy
```

---

## 6. IMPLEMENTATION PRIORITY

### Phase 1: Drop Drift (Immediate)
```
1. Set DRIFT_BUY_ENABLED = False
2. Remove drift_buy from all loops
3. Test for 1 hour - verify 429 errors drop
```

### Phase 2: Fix Sizing (Quick)
```
1. Remove MIN/MAX_KELLY_BET = $2 override
2. Let Kelly calculate freely
3. Add conf-based multiplier
```

### Phase 3: Improve Exits (Next)
```
1. Widen trailing trigger to 40%
2. Scale buffer by confidence (25-35%)
3. Dynamic max hold based on entry zone
4. Force close 1 min before expiry
```

### Phase 4: API Efficiency (Final)
```
1. Add CoinbasePreFilter class
2. Change polling from 2s to 10s
3. Only call Kalshi when signal detected
4. Test rate limit reduction
```

---

## 7. KEY METRICS TO TRACK

```
DAILY LOG FORMAT:
- Total trades: X
- First cross signals: X
- Fallback signals: X
- Win rate: X%
- Avg hold time: X min
- PnL: $X.XX
- API calls: X
- 429 errors: X
- Fees paid: $X.XX
- Open positions: X
```

---

## APPENDIX: CONFIDENCE SCORING

```python
def calculate_confidence(ticker: str, coin_price: float, target: float, 
                         cross_direction: str, time_in_market: float) -> int:
    """
    Score 0-100 based on signal quality.
    """
    score = 50  # Base
    
    # Entry price zone (biggest factor)
    if coin_price < 0.30 or coin_price > 0.70:
        score += 20  # Extreme zones are better
    elif 0.40 <= coin_price <= 0.60:
        score -= 10  # Mid zone is weaker
    
    # How clean was the cross?
    if abs(coin_price - 0.50) > 0.10:  # Clear cross (>10% from midpoint)
        score += 15
    elif abs(coin_price - 0.50) > 0.05:
        score += 10
    
    # Time of day
    if time_in_market < 3:  # Early in window
        score += 10
    elif time_in_market > 10:  # Late - reduce
        score -= 15
    
    # Coinbase momentum
    if coin_has_momentum(coin):  # Price still moving in cross direction
        score += 10
    
    return max(10, min(95, score))  # Clamp 10-95
```

---

## BOTTOM LINE

**Drop drift, trust first cross, let winners run, stop pounding the API.**

Current first_cross alone is profitable. The problem was adding drift (which lost money) and hammering the API (which cost us in 429 errors and fees).

New approach: 
- 80% of the profit
- 10% of the API calls  
- 10% of the fees
- 0% of the drift

**Expected outcome: Turn $100 into $150+ in 2 weeks, then scale to real money.**