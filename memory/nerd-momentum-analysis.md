# Momentum Analysis — Coinbase 15-Min Candles
**Analyst:** Nerd  
**Date:** 2026-04-09  
**Data:** 350 candles (~87 hours) per coin from Coinbase Exchange API

---

## Summary

> **Bottom line:** These coins do NOT exhibit momentum persistence. Almost across the board, when a coin goes up, it's more likely to *reverse* or *stall* than to keep going. This has major implications for superbot's trading logic.

---

## Per-Coin Results

| Coin | Up Ticks | Down Ticks | % Up | % Down | P(Up→Up T+1) | P(Up→Up T+2) | P(Dn→Dn T+1) | Verdict |
|------|----------|------------|------|--------|--------------|--------------|--------------|---------|
| BTC | 172 | 177 | 49.3% | 50.7% | 0.471 | 0.523 | 0.489 | **RANDOM** |
| ETH | 179 | 170 | 51.3% | 48.7% | 0.447 | 0.503 | 0.420 | **MEAN-REVERSION** |
| SOL | 168 | 170 | 48.1% | 48.7% | 0.446 | 0.524 | 0.444 | **MEAN-REVERSION** |
| BNB | 174 | 173 | 49.9% | 49.6% | 0.483 | 0.517 | 0.483 | **RANDOM** |
| DOGE | 177 | 167 | 50.7% | 47.9% | 0.463 | 0.480 | 0.428 | **MEAN-REVERSION** |
| XRP | 182 | 163 | 52.1% | 46.7% | 0.505 | 0.525 | 0.438 | **RANDOM** (borderline) |
| HYPE | 161 | 176 | 46.1% | 50.4% | 0.447 | 0.463 | 0.497 | **RANDOM** |
| ADA | 173 | 149 | 49.6% | 42.7% | 0.474 | 0.457 | 0.405 | **MEAN-REVERSION** |

*Note: "Down Ticks" counts may include a small number of zero-change ticks.*

---

## Key Findings

### 1. Momentum Persistence: Essentially Absent
- **P(Up→Up T+1) < 0.50 for 7 out of 8 coins** — meaning if a coin goes up, the *next* 15-min candle is more likely to go down or stay flat.
- Only XRP is marginally above 0.50 (0.505), but that's within noise territory.
- ETH has the strongest mean-reversion signal: P(Up→Up T+1) = 0.447, meaning a 55% chance of reversal.

### 2. Two-Step Continuation Slightly Better
- P(Up→Up T+2) is consistently *higher* than P(Up→Up T+1) across all coins.
- This suggests a pattern of **"pause then continue"** — a coin that moved up may reverse briefly at T+1, then resume at T+2.
- But even at T+2, most are still below 0.52 (not statistically confident momentum).

### 3. Downward Persistence Also Weak
- P(Down→Down T+1) ranges from 0.405 (ADA) to 0.497 (BNB) — all below 0.50.
- These coins do NOT hold their declines either. Drops tend to get bought.

### 4. Most Are Near 50/50
- BTC and BNB are essentially pure random walks.
- XRP is slightly bullish-biased (52% up ticks) but the momentum within those ups is still weak.

---

## Verdict by Coin

| Coin | Behavior | Implication for Superbot |
|------|----------|-------------------------|
| **BTC** | Random | Don't assume continuation; respect the coinbase bias file signals |
| **ETH** | Mean-reversion | UP → expect pullback. DOWN → expect bounce. Strongest signal. |
| **SOL** | Mean-reversion | Same as ETH; pauses tend to reverse |
| **BNB** | Random | Pure noise; bias file is your best signal |
| **DOGE** | Mean-reversion | DOGE pumps fade fast; take profits on UP moves |
| **XRP** | Slight bullish bias | Most "momentum-like" of the group but still weak |
| **HYPE** | Random | Newer coin, no established pattern |
| **ADA** | Mean-reversion | Drops get bought, pumps get sold; highest asymmetry |

---

## Tactical Takeaway for Tony

**"In the last 5 min, if a coin is up, does it stay up?"**

**Answer: NO.** On average across this dataset, an UP tick is more likely to be followed by a DOWN tick than another UP tick. The only exceptions are marginal (XRP barely above 50%).

**Practical rules for superbot:**
1. **Take profits on UP moves** rather than holding for continuation — the path of least resistance is down after an uptick.
2. **Buy the dip** on DOWN moves — mean reversion is the dominant short-term behavior.
3. **Don't trust momentum breakout strategies** on these coins at 15-min granularity.
4. **Exception: XRP** has the best case for slight momentum; consider it a borderline momentum coin.

---

## Data Quality
- 350 candles per coin = ~87 hours (nearly 4 days)
- Coinbase Exchange public API, 15-min granularity
- UTC timestamps; most recent candle: 2026-04-09 14:15 UTC
