# Live Market Data Analysis
**Data source:** Coinbase streaming data  
**File:** `market_data.jsonl`  
**Records:** 36,557 ticks | **Coins:** BTC, ETH, SOL, XRP, DOGE, BNB, HYPE, ADA  
**Window:** 2026-04-02 17:58:39 → 18:13:04 UTC (~15 minutes)

---

## 1. Volatility Per Coin

| Coin | Std Dev ($) | Std Dev (% of price) | Low | High | Range % |
|------|-------------|----------------------|-----|------|---------|
| BTC | $43.56 | 0.065% | $66,583.47 | $66,795.00 | 0.318% |
| ETH | $1.73 | 0.084% | $2,043.10 | $2,051.39 | 0.406% |
| SOL | $0.103 | 0.131% | $78.41 | $78.92 | 0.647% |
| HYPE | $0.027 | 0.079% | $34.66 | $34.76 | 0.289% |
| ADA | $0.0002 | 0.089% | $0.238 | $0.239 | 0.336% |
| DOGE | $0.0001 | 0.064% | $0.08965 | $0.08991 | 0.290% |
| BNB | $0.36 | 0.062% | $578.33 | $579.93 | 0.277% |
| XRP | $0.0008 | 0.062% | $1.2975 | $1.3016 | 0.316% |

**Key insight:** All coins showed remarkably low volatility during this window (< 0.65% range). SOL was the most volatile (0.65% range), BNB the least (0.28%). BTC, ETH, and SOL have the most absolute dollar swings.

---

## 2. Bid-Ask Spread Analysis

| Coin | Avg Spread (% of price) | Min | Max |
|------|--------------------------|-----|-----|
| BTC | 0.0002% | 0.0000% | 0.022% |
| ETH | 0.0007% | 0.0005% | 0.035% |
| XRP | 0.0097% | 0.0077% | 0.038% |
| SOL | 0.0132% | 0.0127% | 0.064% |
| BNB | 0.0172% | 0.0017% | 0.054% |
| DOGE | 0.0179% | 0.0111% | 0.045% |
| HYPE | 0.0443% | 0.0288% | 0.087% |
| ADA | 0.0451% | 0.0419% | 0.084% |

**Key insight:** BTC and ETH have extremely tight spreads (< 0.001%), making spread-scalping viable. ADA and HYPE have the widest spreads (0.04-0.05%), giving more edge to market makers. Spread scalping on BTC is nearly impossible (spread = ~$0.01 per share at $67k).

---

## 3. Price Momentum (Autocorrelation)

| Coin | Lag-1 Autocorrelation | Interpretation |
|------|------------------------|----------------|
| ADA | -0.448 | STRONG MEAN-REVERTING |
| DOGE | -0.424 | STRONG MEAN-REVERTING |
| ETH | -0.331 | MEAN-REVERTING |
| BTC | -0.172 | MEAN-REVERTING |
| SOL | -0.159 | MEAN-REVERTING |
| BNB | -0.106 | MEAN-REVERTING |
| XRP | -0.065 | MARGINALLY MEAN-REVERTING |
| HYPE | -0.081 | MARGINALLY MEAN-REVERTING |

**Key insight:** ALL 8 coins show negative autocorrelation — meaning prices tend to reverse after moving. This is a strong signal for **mean-reversion strategies** on this data window. ADA and DOGE are the strongest mean-reverters. None of the coins showed trending (positive autocorr) behavior in this window.

---

## 4. Correlation Matrix

| | BTC | ETH | SOL | XRP | DOGE | BNB | HYPE | ADA |
|--|-----|-----|-----|-----|------|-----|------|-----|
| **BTC** | 1.00 | 0.94 | 0.88 | 0.91 | 0.82 | 0.83 | 0.60 | 0.78 |
| **ETH** | 0.94 | 1.00 | 0.80 | 0.90 | 0.65 | 0.75 | 0.51 | 0.69 |
| **SOL** | 0.88 | 0.80 | 1.00 | 0.88 | 0.82 | 0.88 | 0.74 | 0.82 |
| **XRP** | 0.91 | 0.90 | 0.88 | 1.00 | 0.73 | 0.84 | 0.52 | 0.75 |
| **DOGE** | 0.82 | 0.65 | 0.82 | 0.73 | 1.00 | 0.81 | 0.63 | 0.81 |
| **BNB** | 0.83 | 0.75 | 0.88 | 0.84 | 0.81 | 1.00 | 0.67 | 0.83 |
| **HYPE** | 0.60 | 0.51 | 0.74 | 0.52 | 0.63 | 0.67 | 1.00 | 0.70 |
| **ADA** | 0.78 | 0.69 | 0.82 | 0.75 | 0.81 | 0.83 | 0.70 | 1.00 |

**Key insight:** 
- **BTC-ETH correlation is extremely high (0.94)** — they move almost in lockstep
- **HYPE is the most idiosyncratic** (lowest correlation to BTC/ETH)
- **BNB and SOL co-move strongly** (0.88)
- These correlations suggest cross-coin signals are viable (if one spikes, others likely follow)

---

## 5. Tick Rate

| Coin | Total Ticks | Ticks/Second |
|------|-------------|--------------|
| BTC | 10,378 | 11.53 |
| ETH | 7,876 | 8.75 |
| SOL | 7,070 | 7.86 |
| XRP | 5,462 | 6.07 |
| DOGE | 2,653 | 2.95 |
| ADA | 2,605 | 2.89 |
| HYPE | 1,768 | 1.96 |
| BNB | 1,887 | 2.10 |

**Key insight:** BTC and ETH have the highest tick rates, providing more signal for high-frequency strategies. BTC alone generates ~11 ticks/second. HYPE and BNB are the thinnest markets.

---

## 6. Intraday Micro-Patterns

### Round Number Analysis
- **BTC**: 163 round-number crossings (1.57% of ticks) — crosses round numbers frequently
- **SOL**: 597 crossings (8.44% of ticks) — most active at round numbers
- **HYPE**: 37 crossings (2.09%)
- All other coins: ~0% round-number interactions

### Price Distribution
Most coins stayed within ±0.15% of the session VWAP 90% of the time:
- **SOL** is the widest distributed (avg 0.10% from mean, 95th pct = 0.26%)
- **BNB** is the tightest (avg 0.05% from mean, 95th pct = 0.10%)

---

## 7. Signal Viability Assessment

### ✅ Viable Signals for 15-Min Binary Markets

| Strategy | Best Coins | Confidence |
|----------|-----------|------------|
| **Mean-reversion** | ADA, DOGE, ETH | HIGH — strong negative autocorrelation |
| **Cross-coin leading** | BTC→ETH, BTC→XRP | HIGH — BTC leads (94% corr with ETH) |
| **Momentum breakout** | SOL | MEDIUM — widest range, most tick activity |
| **Spread compression** | ADA, HYPE | MEDIUM — wider spreads, more spread movement |
| **Round-number bounce** | SOL, BTC | MEDIUM — SOL crosses round numbers frequently |

### ❌ Difficult Signals
- **Spread scalping on BTC/ETH** — spreads too tight (~0.001%), edge is negligible
- **Pure momentum on this window** — all coins mean-revert; trending strategies would fail

### Recommended Strategy Parameters (for 15-min binary options)
- **Entry threshold**: Price 0.1-0.2% below rolling 5-min avg → BUY
- **Exit threshold**: Price 0.1-0.2% above rolling 5-min avg → SELL  
- **Stop loss**: 0.3% adverse move
- **Best coins**: ADA, DOGE, ETH for mean-reversion; SOL for momentum breakout

### Cross-Coin Signal
Since BTC leads ETH and XRP with 90%+ correlation, a BTC spike 30 seconds ahead could signal ETH/XRP movement. Useful for quick scalps before the 15-min market expires.

---

*Analysis generated from 36,557 live Coinbase ticks | 15-minute window | 2026-04-02*
