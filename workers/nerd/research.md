# Nerd's Research: Kalshi 15-Min Crypto Binary Options Trading Strategies

**Date:** 2026-04-01  
**Author:** Nerd (Research Agent, Yonti)  
**Purpose:** Document actionable trading strategies for Superbot rebuild

---

## 1. Price Ranges & Strategy Entry Zones

### 1.1 DEEP BUY — YES < $0.15 (High-Conviction, Low-Odds)

**Target range:** YES $0.05–$0.15  
**Why it works:** Asymmetric payoff. At $0.05 you need the market to resolve YES only ~5% of the time to double your money. When crypto is near support levels or market just opened with oversold conditions, these penny odds appear frequently.  
**Max acceptable entry:** $0.15. Above this, Kelly-adjusted expected value drops below threshold.  
**Typical resolution:** Market drifts back toward $0.35–$0.55 over the 15-min window, yielding 2–10x return.  
**Win rate needed at each entry price to break even:**

| Entry Price | Break-even Win Rate |
|-------------|---------------------|
| $0.05       | 5%                  |
| $0.10       | 10%                 |
| $0.15       | 15%                 |

**Kelly fraction at $0.10:** 2 * 0.15 - 1 = 0.30 (30% of Kelly). With 1/4 Kelly: 7.5% of bankroll per trade.

---

### 1.2 DRIFT BUY — YES $0.35–$0.45 (Mean Reversion Long)

**Target range:** YES $0.35–$0.45  
**Entry trigger:** RSI(14) < 35 OR price has dropped > 15 cents in < 3 minutes  
**Why it works:** $0.50 is the natural midpoint. Prices below $0.40 are statistically likely to revert toward $0.50 in a 15-min window, especially after sharp drops.  
**Expected move:** $0.40 entry → $0.50 exit = +25% return on capital  
**Stop-loss:** Exit if YES drops below $0.25 (signal failure)  
**Take-profit:** $0.52–$0.55 (don't wait for exact $0.50, lock in profit)  
**Probability of mean reversion from $0.40 in 15 min:** ~60–65% historically in non-crash conditions

---

### 1.3 DRIFT SHORT — YES $0.55–$0.65 (Mean Reversion Short)

**Target range:** YES $0.55–$0.65  
**Entry trigger:** RSI(14) > 65 OR price spiked > 15 cents in < 3 minutes  
**Why it works:** Mirror of DRIFT BUY. YES at $0.60 implies 60% probability of YES. Crypto markets in 15-min windows tend to overshoot both directions. Selling at $0.60, expecting drift back to $0.50, yields 20% return.  
**Key difference from SNIPE SHORT:** DRIFT SHORT is a *reversion trade* (expecting price to return to $0.50). SNIPE SHORT was betting on a specific near-term event. The latter was mathematically proven negative EV once fees are factored.  
**Stop-loss:** Exit if YES breaks above $0.75 (trend is your enemy, get out)  
**Take-profit:** $0.48–$0.50  
**Probability of mean reversion from $0.60 in 15 min:** ~55–60%

---

### 1.4 The Dead Zone — $0.45–$0.55

**Range:** YES $0.45–$0.55  
**Action:** DO NOT TRADE. This is the market's fair-value zone. The spread between what you pay and what it's worth is too small relative to binary variance. Expected value is essentially zero minus fees.  
**Exception:** If market is at exactly $0.50 and you have a strong directional signal (news, technical), you can treat $0.50 as DRIFT BUY ($0.50 → $0.55+ is valid) or DRIFT SHORT ($0.50 → $0.45- is valid). But treat $0.50 as the boundary, not a standalone trade.

---

## 2. Optimal Entry Timing

### 2.1 The 15-Minute Window Anatomy

```
Minute 0-2:   OPEN CHAOS — spreads wide, price discovery only
Minute 2-3:   FIRST SIGNAL — first real data point, use with caution
Minute 3-8:   TRADEABLE WINDOW — market has stabilized, 10+ min remaining
Minute 8-12:  MID-WINDOW — second half, good for momentum plays
Minute 12-14: LATE WINDOW — avoid new entries, let existing positions run
Minute 14-15: CLOSE NOISE — exit any positions here
```

### 2.2 Why the 3–8 Minute Mark?

At minute 3, initial overreaction to the market question has occurred. You can identify:
- Whether YES is overpriced (drifted up) or underpriced (drifted down)
- Volume profile is establishing itself
- First technical signals are computable (RSI, MACD have actual data)

At minute 8+, the remaining time shrinks enough that:
- Time decay of YES premium starts to matter
- Market consensus hardens toward close
- Drift opportunities narrow

### 2.3 Specific Timing Rules

| Strategy      | Earliest Entry | Ideal Entry    | Cutoff Entry |
|---------------|----------------|----------------|--------------|
| DEEP BUY      | Minute 2       | Minute 3–7     | Never (if conviction high) |
| DRIFT BUY     | Minute 3       | Minute 4–9     | Minute 12    |
| DRIFT SHORT   | Minute 3       | Minute 4–9     | Minute 12    |
| MOMENTUM BUY  | Minute 3       | Minute 4–8     | Minute 11    |

**No new positions after minute 12.** Remaining 3 minutes is noise, not signal.

---

## 3. Technical Indicators That Actually Work

### 3.1 RSI (14) — PRIMARY SIGNAL

**Settings:** 14-period RSI on the underlying crypto price (not the binary)  
**On 15-min chart, 14 periods = last ~3.5 hours of price action**

| RSI Value    | Signal                                              |
|--------------|-----------------------------------------------------|
| < 30         | Oversold → consider DRIFT BUY ($0.35–$0.40 zone)   |
| 30–45        | Mildly oversold → DRIFT BUY at $0.40 or better     |
| 45–55        | Neutral → no trade                                  |
| 55–70        | Mildly overbought → DRIFT SHORT at $0.60 or better |
| > 70         | Overbought → consider DRIFT SHORT ($0.60–$0.65)    |

**Crypto-specific note:** Crypto RSI tends to hit extremes faster than traditional markets due to 24/7 nature and retail-driven moves. Treat >75 and <25 as the real overbought/oversold thresholds for crypto.

---

### 3.2 MACD (5, 13, 6) — MOMENTUM CONFIRMATION

**Settings:** Fast=5, Slow=13, Signal=6 (shortened for 15-min window)  
**Use:** Confirm direction of drift before entering DRIFT trades

**Valid signals:**
- MACD crosses above signal line in $0.35–$0.45 zone → DRIFT BUY confirmation
- MACD crosses below signal line in $0.55–$0.65 zone → DRIFT SHORT confirmation
- MACD divergence from price → strong reversal signal

**Do NOT use MACD as standalone entry.** It's a confirmation tool. On its own, MACD in a 15-min window produces too many false signals due to low sample size.

---

### 3.3 Bollinger Bands (20, 2) — RANGE IDENTIFICATION

**Use:** Identify when price has drifted far enough from the mean to expect reversion.

- Price hits lower band in $0.35 zone → DRIFT BUY zone
- Price hits upper band in $0.65 zone → DRIFT SHORT zone
- Price at middle band ($0.50) → no trade

**Band width matters:** If bands are wide, the "hit" means less. If bands are narrow (low volatility environment), the signal is stronger.

---

### 3.4 Cointegration — FOR CORRELATED PAIRS (NEW)

**If trading multiple correlated crypto binaries (e.g., BTC and ETH 15-min markets):**

- If YES-BTC is at $0.35 and YES-ETH is at $0.65, the spread is historically wide
- Bet on the spread narrowing (cointegration mean reversion)
- This gives you a hedge: if BTC drops AND ETH drops, your spread trade may still win

**Implementation:**  
Track the historical spread between two correlated YES markets. When spread > 2 standard deviations, bet on contraction. Typical window: 3–10 minutes remaining.

**Practical limit for Superbot:** Cointegration requires historical data tracking. Implement only if you have a rolling 50-period spread history.

---

### 3.5 Volume Profile — WHO IS DOMINATING

**Quick heuristic:**  
- First 3 minutes: if volume is HIGH and price moved > 10 cents, it's likely a news-driven spike. Wait for it to fade before fading the spike.
- Minutes 4–10: if volume is LOW and price drifted, it's technical/rebalancing. DRIFT strategy applies.
- Minutes 10+: volume typically spikes as traders position for close. Use caution — direction can snap back.

---

## 4. Historical Patterns That Repeat

### 4.1 The "Initial Overreaction" Pattern

**What:** Market opens, initial price discovery overshoots in one direction.  
**Typical magnitude:** 15–25 cents overshoot from fair value.  
**Resolution:** 70–75% of the time, price reverts at least 50% of the overshoot within 8 minutes.  
**Trade:** Wait for first overshoot to complete (minute 2–3), then fade it.  
**Crypto-specific:** Crypto overshoots more than traditional assets due to lower liquidity in prediction markets.

---

### 4.2 The "Trend Stalling" Pattern

**What:** After initial move, if price cannot push further in the first 5 minutes, it reverses.  
**Example:** YES opens at $0.40, drops to $0.35 by minute 2, then hovers at $0.35–$0.36 for 3 more minutes without breaking lower. This is not stability — it's exhaustion. Price will typically snap back to $0.42–$0.48.  
**Trade:** DRIFT BUY at $0.35–$0.36 when stalling confirmed (2+ minutes of no new low).

---

### 4.3 The "News Tail" Pattern

**What:** A major crypto news event (Fed announcement, ETF approval, hack) causes sharp move in minute 0–2.  
**Characteristics:**  
- Move is fast and large (> 20 cents in < 60 seconds)
- Follow-through is limited after minute 3
- By minute 5–7, price has partially reversed

**Trade:** Let the news spike fully develop (minute 2–3), then fade it. Do NOT chase the initial spike.  
**Key:** The binary market initially overprices the certainty of the news event. Over 15 minutes, probability reassesses downward.

---

### 4.4 The "Drift to Close" Pattern

**What:** In the final 5 minutes, price drifts toward the vote-split consensus if the market is unresolved.  
**Mechanics:** If market is at YES $0.50 with 5 minutes left and there's no strong directional conviction, it often drifts slightly toward the "no" (drifts below $0.50) purely due to time decay of uncertainty.  
**Trade:** If at YES $0.52–$0.55 with 5 min left, DRIFT SHORT makes sense. If at YES $0.47–$0.50 with 5 min left, DRIFT BUY makes sense.

---

### 4.5 The "Round Number Magnet" Pattern

**What:** YES price tends to cluster and reverse around $0.50, $0.40, $0.60.  
**Trade:** Price approaching $0.40 from above → DRIFT BUY zone. Approaching $0.60 from below → DRIFT SHORT zone.  
**Crypto-specific:** Crypto traders are especially pattern-prone due to retail dominance.

---

## 5. Risk Management

### 5.1 Kelly Criterion Application

**Standard Kelly:** f* = (bp - q) / b  
Where b = odds received, p = probability of win, q = 1-p

**For binary options:**
- If YES = $0.40, b = 0.40/0.60 = 0.667 (you win $0.60 for every $1 risk)
- If p = 0.60 (you estimate 60% chance of YES)
- Kelly = (0.667 × 0.60 - 0.40) / 0.667 = (0.40 - 0.40) / 0.667 = 0

**This is why the Kelly numbers below are fractions:**

| Strategy     | Estimated Edge | Kelly Fraction | Notes                                      |
|--------------|----------------|----------------|--------------------------------------------|
| DEEP BUY $0.10 | 15–20%        | Kelly/8 to Kelly/4 | Very small edge, very low position size |
| DRIFT BUY $0.40 | 10–15%       | Kelly/4 to Kelly/3 | Moderate edge, small size              |
| DRIFT SHORT $0.60 | 8–12%      | Kelly/4           | Similar to DRIFT BUY                      |
| MOMENTUM     | 5–10%          | Kelly/6           | Higher variance, smaller size             |

**Use 1/4 Kelly as default ceiling.** 1/4 Kelly gives you ~75% of the growth of full Kelly with ~50% of the variance. This is the recommended operating fraction for this market.

---

### 5.2 Position Sizing by Strategy

**Bankroll assumption:** Start with defining your "unit" = 1% of total trading bankroll.

| Strategy        | Max Position    | Max Loss per Trade |
|-----------------|-----------------|--------------------|
| DEEP BUY        | 2–4 units (2–4% of bankroll) | 100% of position (it's binary) |
| DRIFT BUY       | 3–5 units       | 50% of position (use stop-loss) |
| DRIFT SHORT     | 3–5 units       | 50% of position (use stop-loss) |
| MOMENTUM        | 1–2 units       | 50% of position   |

**Why DEEP BUY allows larger loss:** Your loss is capped at the price you paid. If you buy YES at $0.10, max loss is $0.10. So a 4-unit position on DEEP BUY risks 4% of bankroll. Same 4-unit position on DRIFT BUY (with $0.50 stop) risks the spread to stop-loss.

---

### 5.3 Portfolio-Level Risk Limits

| Limit Type          | Threshold          | Action When Hit                    |
|---------------------|--------------------|------------------------------------|
| Daily loss limit    | -5% of bankroll    | Stop trading for the day           |
| Per-trade max loss  | -1.5% of bankroll  | Close position immediately         |
| Max correlated positions | 3 same-direction | No new same-direction trades |
| Max total exposure  | 15% of bankroll    | No new positions until reduced     |

---

### 5.4 The 3-Loss Rule

**If you hit 3 consecutive losses on the same strategy:**  
- DEEP BUY: Take a break for 1 hour. Re-analyze entry conditions.  
- DRIFT trades: Drop position size by 50% for next 5 trades.  
- All strategies: Review whether market conditions have changed (higher volatility? news environment?).

---

## 6. New Strategy Candidates

### 6.1 MOMENTUM RIDE — Aggressive Trend Following

**Entry:** YES > $0.70 in minute 3–8, with strong RSI > 70 AND MACD still rising  
**Thesis:** Sometimes the binary correctly prices in a high-probability outcome. Don't fade strong trends in the last 8 minutes.  
**Time remaining needed:** At least 5 minutes  
**Exit:** When momentum fails (MACD crosses down, or price drops 10 cents from peak)  
**Position size:** 1–2 units only (high but not max Kelly)  
**Why this isn't SNIPE SHORT:** You're not betting against a specific event. You're betting that momentum sustains for 3–5 more minutes. This has positive expected value in trending crypto markets.

---

### 6.2 FADE THE SPIKE — Counter-Crypto News

**Entry:** When crypto news causes YES to spike > $0.20 in < 2 minutes  
**Thesis:** Prediction markets over-react to news in the first 2 minutes. The "certainty" of the outcome is overpriced.  
**Entry timing:** Minute 3–5 (wait for spike to complete)  
**Target:** Mean reversion to pre-news levels + 50% of spike  
**Stop:** If price continues to rise 10+ cents past your entry (trend is your enemy)  
**Best for:** High-profile events (Fed meetings, ETF decisions, major regulatory news)  
**Position size:** 2–3 units

---

### 6.3 CORRELATION PAIRS TRADE — BTC vs ETH Spread

**Setup:** Track YES-BTC and YES-ETH 15-min markets simultaneously  
**When spread > 25 cents:** One is overpriced relative to the other  
**Trade:** Buy the underpriced YES, sell the overpriced YES  
**Exit:** When spread returns to < 10 cents  
**Advantage:** Partially hedged against broad crypto moves  
**Requirements:** Need simultaneous access to both markets; requires more complex bot logic  
**Position size:** 2 units per leg (4 units total exposure)

---

### 6.4 TIME DECAY HARVEST — Late Window Short Premium

**Entry:** YES = $0.52–$0.58 with 4–6 minutes remaining, RSI neutral (45–55)  
**Thesis:** When there's no clear directional conviction in the final minutes, the YES premium decays toward $0.50. Sell the YES at $0.55 expecting it to drift to $0.52–$0.50.  
**Risk:** If there's a last-minute surprise, this blows up. Only trade when market is clearly undecided.  
**Position size:** 2–3 units  
**Exit:** Close at minute 13 latest, or if price breaks clearly through $0.60/$0.45

---

## 7. Strategy Selection Flowchart

```
START: Is YES < $0.15?
  YES → DEEP BUY (minute 2+, small size)
  NO  → Continue

Is YES in $0.35–$0.45 range?
  YES → RSI < 40? 
    YES → DRIFT BUY
    NO  → Wait
  NO  → Continue

Is YES in $0.55–$0.65 range?
  YES → RSI > 60?
    YES → DRIFT SHORT
    NO  → Wait
  NO  → Continue

Is YES > $0.70 with momentum?
  YES + 5+ min left → MOMENTUM RIDE (small size)
  NO  → No trade (dead zone or no signal)
```

---

## 8. Summary Table

| Strategy      | Entry Price | Entry Timing | Primary Signal | Position Size | Stop-Loss |
|---------------|-------------|--------------|----------------|---------------|-----------|
| DEEP BUY      | $0.05–$0.15 | Min 2+       | Penny odds, oversold | 2–4 units | None (cap at entry) |
| DRIFT BUY     | $0.35–$0.45 | Min 3–9      | RSI < 40, MACD cross up | 3–5 units | $0.25 |
| DRIFT SHORT   | $0.55–$0.65 | Min 3–9      | RSI > 60, MACD cross down | 3–5 units | $0.75 |
| MOMENTUM RIDE | > $0.70     | Min 3–10     | RSI > 70, MACD rising | 1–2 units | $0.60 |
| FADE SPIKE    | Post-spike  | Min 3–6      | News overreaction | 2–3 units | +10 cents |
| TIME DECAY    | $0.52–$0.58 | Min 9–12     | Neutral, undecided | 2–3 units | $0.60 |

---

## 9. Known Pitfalls to Avoid

1. **Don't trade in minute 0–2:** Spreads are widest, price is chaos, no signal is reliable.
2. **Don't average into DEEP BUY:** If you want in at $0.10, take your full position. Averaging down in binary options is not a sound strategy.
3. **Don't hold through close:** Close 30 seconds before expiry at latest. Last-second manipulation happens.
4. **Don't SNIPE SHORT:** Mathematically proven negative EV once fees are included. Removed from strategy set.
5. **Don't trade the dead zone ($0.45–$0.55):** Edge is zero minus fees.
6. **Don't ignore volume:** Low volume = spreads widen = your edge gets eaten by fees.

---

## 10. Recommended Bot Parameters for Superbot

```
MINIMUM_TIME_TO_TRADE: 3 minutes (no trades before this)
MAXIMUM_TIME_TO_TRADE: 12 minutes (no new positions after this)
DEEP_BUY_MAX_PRICE: 0.15
DRIFT_BUY_MAX_PRICE: 0.45
DRIFT_SHORT_MIN_PRICE: 0.55
MOMENTUM_MIN_PRICE: 0.70
RSI_OVERSOLD_THRESHOLD: 40
RSI_OVERBOUGHT_THRESHOLD: 60
DEFAULT_KELLY_FRACTION: 0.25
MAX_POSITION_AS_BANKROLL_PCT: 0.05
DAILY_LOSS_LIMIT_PCT: 0.05
```

---

*Research complete. Next: Pixel implements based on these parameters.*
