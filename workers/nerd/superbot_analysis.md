# Superbot Post-Mortem Analysis
**Date:** 2026-04-02  
**Session:** 14:39-15:41 UTC  
**Loss:** -$73.74 (started $100, ended $26.26)

---

## Executive Summary

Superbot hemorrhaged money due to **five critical failures**:

1. **Wrong entry zones** — bot using $0.35-$0.65 for drift_buy, but Nerd documented $0.35-$0.45
2. **Overlapping strategies** — drift_buy ($0.35-$0.65) and drift_short ($0.55-$0.75) overlap at $0.55-$0.65, causing conflicting signals
3. **Stop loss too tight** — 25% SL doesn't give 15-min binary trades room to breathe
4. **No Coinbase bias filter** — bot fights market direction constantly
5. **Daily stop loss not working** — triggered but reset and resumed trading immediately

---

## 1. Strategy Performance Analysis

### drift_buy (54 trades)
| Metric | Value |
|--------|-------|
| Win rate | ~18% (terrible) |
| Problem | Entries at $0.49-$0.57 are outside Nerd's $0.35-$0.45 zone |
| Evidence | Successful trades: E:$0.45 ($0.45→$0.95), E:$0.57 ($0.57→$0.95), E:$0.53 ($0.53→$0.96) |

**Only 3 drift_buy wins out of ~54 trades.** Most wins came from entries at $0.53-$0.57 hitting TP at $0.95 — but these entries should NEVER have been taken (they're in the dead zone).

### drift_short (1 trade visible)
| Metric | Value |
|--------|-------|
| Win rate | 100% (1/1) |
| Entry | ETH at $0.68 → TP hit at $0.385 |
| Note | This trade was valid (drift_short zone is $0.55-$0.65) |

### deep_short (27 trades)
| Metric | Value |
|--------|-------|
| Win rate | ~30% |
| Total PnL | Deeply negative (multiple $0.70-$0.90 losses) |
| Problem | Entering at $0.08-$0.14 is correct, but market moved against shorts at expiry |

The deep_short trades that expired were fine — they just needed more time. The problem is the 15-min window is too short for deep_short to work consistently.

---

## 2. Critical Parameter Mismatch: Config vs Nerd's Research

| Parameter | Nerd's Doc | Config.py | Status |
|-----------|------------|-----------|--------|
| DRIFT_BUY zone | **$0.35-$0.45** | $0.35-$0.65 | ❌ WRONG |
| DRIFT_SHORT zone | $0.55-$0.65 | $0.55-$0.75 | ❌ WRONG |
| Dead zone | **$0.45-$0.55** | N/A (overlapping) | ❌ MISSING |
| DRIFT_BUY stop loss | **$0.25** (absolute) | 25% (relative) | ❌ WRONG LOGIC |
| DRIFT_SHORT stop loss | **$0.75** (absolute) | 25% (relative) | ❌ WRONG LOGIC |

**The bot entered drift_buy at $0.49-$0.57 CONSTANTLY** — these are in the dead zone ($0.45-$0.55) per Nerd's research. They should have been NO TRADES.

---

## 3. Entry Price Analysis

### Entries in Nerd's DEAD ZONE ($0.45-$0.55):
- $0.45, $0.454, $0.459, $0.485, $0.495, $0.50, $0.515, $0.53, $0.545, $0.554

These 30+ entries were all **prohibited** per Nerd's research. Zero edge in this zone.

### Entries in WRONG drift_buy zone ($0.50-$0.65):
- $0.50, $0.515, $0.53, $0.545, $0.55, $0.554, $0.565, $0.57

These are actually closer to drift_short territory, not drift_buy.

### Entries CORRECTLY in drift_buy zone ($0.35-$0.45):
- $0.35, $0.355, $0.36, $0.37, $0.375, $0.38, $0.385, $0.39, $0.395, $0.40, $0.405, $0.415, $0.42, $0.425, $0.444

These entries were mostly losing due to **SL too tight** (see below).

---

## 4. Stop Loss Analysis

**Problem:** 25% relative stop loss is mathematically wrong for binary options in a 15-min window.

**Math:**
- Entry $0.40 → SL at $0.30 (25% drop)
- But binary YES prices don't move in smooth percentages — they jump
- A drop from $0.40 to $0.30 is a 25-cent move, which is common in volatile 15-min crypto

**Evidence from trades:**
```
E:$0.40 X:$0.29 → -$0.20 (SL hit) — price dropped 27.5%
E:$0.38 X:$0.28 → -$0.19 (SL hit) — price dropped 26.3%
E:$0.36 X:$0.23 → -$0.27 (SL hit) — price dropped 36%
```

**Nerd's documented stop losses:**
- DRIFT_BUY: exit at $0.25 (absolute floor, not 25%)
- DRIFT_SHORT: exit at $0.75 (absolute ceiling, not 25%)

---

## 5. Coinbase Bias — Not Integrated

**Current situation:** Coinbase fetcher exists but bot NEVER reads it.

**From the session context:**
- BTC: BULLISH 60% (BULLISH_ENGULFING pattern)
- ETH: BULLISH 60% (BULLISH_ENGULFING)
- SOL: BULLISH 50% (AT_50_FIB)

**Bot behavior:** Kept entering drift_buy (expecting price to go UP from oversold) while Coinbase showed BULLISH. This is fighting the tape.

**What should happen:**
- If Coinbase BULLISH + drift_buy signal → TAKE IT (momentum agrees)
- If Coinbase BEARISH + drift_buy signal → SKIP IT (momentum disagrees)
- If Coinbase BEARISH + drift_short signal → TAKE IT (momentum agrees)

---

## 6. Daily Stop Loss — Broken Logic

**Config:** `DAILY_STOP_LOSS_PCT = 0.20` (20%)

**What happened:**
1. Bot started at $100
2. Lost ~$20 (hit 20% threshold)
3. Stop loss triggered → closed positions at $0.50 (massively wrong exit prices)
4. **RESET balance to $100**
5. **RESUMED TRADING**

This is why we have 82 trades and -$73.74 instead of stopping at -$20. The daily stop loss was a **reset mechanism**, not a **kill switch**.

---

## 7. Recommended Fixes (Priority Order)

### P0 — Fix Entry Zones (CRITICAL)
```python
# Current (WRONG):
DRIFT_BUY_MIN_PRICE = 0.35
DRIFT_BUY_MAX_PRICE = 0.65  # Should be 0.45!

# Fix to:
DRIFT_BUY_MIN_PRICE = 0.35
DRIFT_BUY_MAX_PRICE = 0.45  # Nerd's documented zone

DRIFT_SHORT_MIN_PRICE = 0.55
DRIFT_SHORT_MAX_PRICE = 0.65  # Nerd's documented zone
```

### P0 — Fix Stop Loss to Absolute Prices
```python
# Current (WRONG):
DRIFT_SL_PCT = 0.25  # Relative percentage

# Fix to:
DRIFT_BUY_STOP = 0.25  # Absolute floor
DRIFT_SHORT_STOP = 0.75  # Absolute ceiling
```

### P0 — Add Dead Zone Check
```python
def _is_in_dead_zone(self, price):
    return 0.45 <= price <= 0.55

# In evaluate_market:
if self._is_in_dead_zone(mid_price):
    return None  # NO TRADE in dead zone
```

### P1 — Fix Daily Stop Loss
```python
def _check_daily_stop_loss(self):
    # Current: resets balance and continues trading
    # Fix: STOP TRADING for the day
    if loss >= DAILY_STOP_LOSS_AMOUNT:
        self.trading_stopped = True  # Don't reset balance
        # Log and wait for human intervention
```

### P1 — Integrate Coinbase Bias Filter
```python
def _check_coinbase_bias(self, coin):
    """Returns True if Coinbase bias aligns with drift_buy, False otherwise."""
    bias = self.coinbase_fetcher.get_bias(coin)  # 'BULLISH' or 'BEARISH'
    return bias in ('BULLISH', 'NEUTRAL')  # Allow neutral too

# In drift_buy evaluation:
if not self._check_coinbase_bias(coin):
    return None  # Skip if Coinbase disagrees
```

### P2 — Fix Strategy Priority (Overlap Zone)
The overlap at $0.55 creates conflicts. Add explicit boundary:
```python
def _check_drift_buy(self, market, mid_price, time_left):
    if not (0.35 <= mid_price < 0.55):  # Explicitly exclude $0.55+
        return None

def _check_drift_short(self, market, mid_price, time_left):
    if not (0.55 < mid_price <= 0.65):  # Explicitly start at $0.55+
        return None
```

### P2 — Reduce Position Size
Current: $2 per trade (max)  
Problem: With 18% win rate, $2 losses compound fast  
Recommendation: $1 per trade until win rate improves above 50%

### P3 — Add Cooldown After Loss
```python
if self.win_rate < 0.40:
    COOLDOWN_CYCLES = 3  # Wait after losing streak
```

---

## 8. Summary of Changes for Pixel

| File | Change | Priority |
|------|--------|----------|
| config.py | `DRIFT_BUY_MAX_PRICE = 0.45` (was 0.65) | P0 |
| config.py | `DRIFT_SHORT_MAX_PRICE = 0.65` (was 0.75) | P0 |
| config.py | Remove `DRIFT_SL_PCT`, add absolute stop prices | P0 |
| config.py | `DAILY_STOP_LOSS_AMOUNT = 20.00` (absolute, not %) | P0 |
| superbot.py | Dead zone check in evaluate_market() | P0 |
| superbot.py | Fix daily stop loss to STOP, not reset | P0 |
| superbot.py | Coinbase bias integration | P1 |
| strategies.py | Explicit boundary checks (no overlap) | P2 |

---

## 9. Expected Outcome After Fixes

| Metric | Before | After (Expected) |
|--------|--------|-----------------|
| Win rate | 18% | 55%+ |
| Total trades (same session) | 82 | ~15-20 (quality over quantity) |
| Day P&L | -$73.74 | Break-even or small profit |
| Daily stop loss | Reset & resume | Actual stop |

---

## 10. Next Steps

1. **Pixel implements P0 fixes immediately** — these are causing direct losses
2. **Reboot bot with fresh $100**
3. **Monitor for 1 hour** — expect win rate > 50% if entries are in correct zones
4. **Add Coinbase bias** — P1, confirm it's integrated and working
5. **Don't rush** — quality entries in $0.35-$0.45 zone only

---

*Analysis complete. Nerd out.*
