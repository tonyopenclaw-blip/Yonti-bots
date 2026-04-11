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
