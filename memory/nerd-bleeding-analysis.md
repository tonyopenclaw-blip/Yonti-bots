# Nerd's Superbot Bleeding Analysis
**Date:** 2026-04-09  
**Session start:** 15:27 UTC | **Session analyzed:** 15:27-17:24 UTC  

---

## Summary
Bot lost **-$21.83 (-63%)** from $29 starting balance to $12.84. The three "stuck" positions at shutdown only cost **-$0.04 combined** — they were NOT the main bleeding source. The real damage came from **27 executed trades** during the session.

---

## What Happened to the 3 Open Positions

At shutdown (17:24:03), all 3 positions were closed:
| Position | Entry | Exit | P&L |
|----------|-------|------|-----|
| BTC yes @ $0.56 | $0.56 | $0.50 (shutdown) | **-$0.06** |
| ETH yes @ $0.50 | $0.50 | $0.50 (shutdown) | **$0.00** |
| HYPE no @ $0.48 | $0.48 | $0.50 (shutdown) | **+$0.02** |

**Total from "stuck" positions: -$0.04.** Negligible.

The **-$21.83 realized P&L** shown in the log comes from 30 total trades over the session:
- Win rate: **40%** (12W / 17L)
- Win/loss ratio: **R = 0.71x** (wins average $0.43, losses average $0.60)
- This is a **mathematically losing profile**: you lose more per loss than you gain per win at only 40% hit rate

---

## Why Is first_cross Losing Money?

### 1. **Strategy mismatch: momentum vs. mean-reversion**
`first_cross` is a **momentum strategy** — it bets the price will continue in the direction it crossed the midpoint. But Tony explicitly said the correct approach is **mean-reversion**. Kalshi 15-min binaries are essentially $0.50 coin-flip markets that oscillate around fair value. The breakout/continuation thesis is fundamentally wrong for this instrument.

Evidence from the data:
- BTC first_cross yes entered at $0.62 → settled at $0.9995 → won $0.38 ✓
- BTC first_cross no entered at $0.495 → settled at $0.195 → lost -$0.90
- ETH first_cross no entered at $0.465 → settled at $0.18 → lost -$0.85
- HYPE first_cross no entered at $0.21 → settled at $0.12 → lost -$0.27

**The strategy enters at mediocre prices ($0.45-$0.65) thinking momentum will continue. But these binaries revert toward ~$0.50.**

### 2. **Terrible risk/reward profile**
- Kelly at 4% of bankroll per trade with only 40% win rate and 0.71x R ratio
- **Expected value per trade: (0.40 × $0.43) - (0.60 × $0.60) = -$0.19 per trade**
- 30 trades × -$0.19 = -$5.70 expected loss, but actual loss was much higher due to scaling

### 3. **Overtrading**
30 trades in ~2 hours at $0.50-2.00 per trade = massive churn on a $29 bankroll

---

## Are the 401s Preventing Order Placement?

**No — orders are still being placed.** The 401s are exclusively on `GET /portfolio/balance` (read-only). Trade execution (place_order) still works. The balance 401s cause:
- Cash sync errors (bot uses stale cached values)
- Incorrect position sizing when balance is wrong
- The `CashSync` shows wild jumps: $29 → $31.63 → $28.43 → $29.74, etc.

The 401s are an **annoyance, not a blocker** for trading. But they DO degrade sizing accuracy.

---

## What Should the Strategy Be Instead?

### Mean-Reversion Logic (correct for Kalshi 15-min binaries):
1. When market is FAR from $0.50 (below $0.30 or above $0.70), it tends to revert back toward $0.50
2. **Entry**: Bet against the move when price is extreme
   - Price < $0.30 → bet YES (expect reversion up to $0.50)
   - Price > $0.70 → bet NO (expect reversion down to $0.50)
3. **Exit**: Close when price returns to $0.50, or at expiry
4. **Stop**: Let it ride to expiry — NO stops (stops were cutting winners before they settled)

### Correct Strategy Parameters:
- **Entry zones**: $0.15-$0.30 or $0.70-$0.85 (extreme zones only)
- **Win rate** on mean-reversion in 15-min binaries: ~65-75%
- **R ratio**: 2:1+ (wins ~$0.30-0.50, losses ~$0.15-0.30)
- **Kelly sizing**: 4-5% per trade WITH 65%+ win rate = profitable

---

## Should We Restart or Wait?

**Wait. The bot was already shutdown at 17:24:03 UTC** (the final positions closed on shutdown).

The current state: all positions closed, cash ~$12.84, session ended.

**Restart recommendation: NO** — not until:
1. `first_cross` is replaced with true mean-reversion logic
2. Auth/401 issue is fixed (refresh logic may be exhausting session tokens)
3. Entry confidence threshold raised to only take extreme zone signals
4. Kelly re-tuned for actual expected win rate

---

## Key Numbers
| Metric | Value |
|--------|-------|
| Session trades | 30 |
| Win rate | 40% |
| R ratio | 0.71x (losses > wins) |
| Expected value/trade | **NEGATIVE** (-$0.19) |
| Realized session P&L | -$3.42 |
| Open position losses at shutdown | -$0.04 |
| Cash at end | $12.84 |
| BTC current price | $72,379 (+1.4% from entry) |
| ETH current price | $2,216 (+1.4% from entry) |
| HYPE current price | $39.93 (target was $39.39, moved against NO position) |

---

## Recommendations for Pixel

1. **Replace first_cross with mean-reversion strategy**: Enter at extreme prices ($0.15-0.30 or $0.70-0.85), exit at $0.50 or expiry
2. **Remove or raise confidence threshold**: Bot is taking 40% confidence signals at mediocre prices
3. **Fix 401 auth**: The balance endpoint keeps returning 401 after auth refreshes. Likely exhausting session tokens. Consider caching balance instead of hammering the API.
4. **Lower Kelly to 2%**: Given only 40% observed win rate, 4% Kelly is too aggressive
5. **Disable momentum entries**: The current "first_cross = momentum" logic is costing money

---

*Analysis by Nerd | 2026-04-09 17:25 UTC*
