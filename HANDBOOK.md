# HANDBOOK.md — Yonti Knowledge Base

_This is Tony's compressed knowledge, decompressed and organized by Jenkins._

> **Incoming protocol:** When Tony sends "x" knowledge, I decompress it here and integrate it into bot strategies, research, and tooling.

---

## 📡 KALSHI LEARNING

### Platform Notes
- API: `api.elections.kalshi.com`
- Auth: `KALSHI-ACCESS-KEY` header
- Fee: 1.6% on winnings
- Markets close 4 hours AFTER resolution time

### Active Series
- Crypto 15-min: KXBTC15M, KXETH15M, KXSOL15M, KXXRP15M, KXDOGE15M, KXBNB15M, KXHYPE15M, KXADA15M
- NBA Game Winners: KXNBAGAME
- NHL Game Winners: KXNHLGAME
- Ticker format: `KXBTC15M-YYMMDDHHMM-00`

### Known Gaps (From Tony's Research)
- Kalshi API for sports returns PRE-GAME static odds only
- Live in-game odds only visible on website
- Need websocket or alternative API for live sports odds
- CLOB (Central Limit Order Book) from Coinbase — not yet integrated

---

## 🏛️ POLYMARKET LEARNING

### Platform Notes
_(Tony to fill in API details, auth requirements, market structure)_

### Known Gaps
- Not yet integrated into any bot
- Need to research market structure, fee structure, API access

---

## 🧮 TRADING FORMULA IMPROVEMENTS

### Enhanced Kelly Criterion (Standard Industry Approach)

**The Formula:**
```
f* = (bp - q) / b
Where:
  p = your estimated true probability
  q = 1 - p
  b = net odds = (1 - market_price) / market_price
```

**Quick Reference Table:**

| Your Edge | Full Kelly | Half Kelly (Recommended) | Quarter Kelly |
|-----------|-----------|-------------------------|---------------|
| 5%        | 10%       | 5%                      | 2.5%          |
| 10%       | 20%       | 10%                     | 5%            |
| 15%       | 30%       | 15%                     | 7.5%          |
| 20%+      | 40%+      | 15% (cap)               | 10%           |

**Why Half-Kelly?**
- Captures ~75% of theoretical max growth rate
- Cuts variance/drawdowns by ~50%
- Protects against probability estimation errors
- Full Kelly = 2x overbet = same growth as $0 bet

**Kelly for Prediction Markets (Simplified):**
```
Kelly % = (Your_Prob - Market_Price) / (1 - Market_Price)
```
Example: Market = $0.60 (60%), Your estimate = 75%
Kelly = (0.75 - 0.60) / (1 - 0.60) = 0.375 = 37.5% → Half Kelly = ~19%

---

### Exit Rules (from polymarket-bot reference implementation)

| Rule | Trigger | Action |
|------|---------|--------|
| **Stop-Loss** | Position down >25% from entry | SELL immediately |
| **Take-Profit** | Price reaches $0.95+ | SELL to lock gains |
| **Edge-Gone** | Market moved past your original fair estimate | SELL, book the profit/loss |
| **Re-estimate** | Price moved >10% from entry | Re-run AI ensemble, adjust or exit |
| **Cooldown** | Closed a position | Block re-entry for 2 cycles |
| **Low-Confidence Skip** | Ensemble std dev >10% | SKIP — don't trade |

---

### Entry Rules (What Our Bots Are Missing)

1. **Minimum edge threshold:** Only trade if mispricing > 10% between your estimate and market price
2. **Confidence filter:** Skip markets where probability estimates are inconsistent (high std dev)
3. **Penny position skip:** Don't touch markets where price < $0.01 (can't exit efficiently)
4. **Liquidity check:** Verify volume/spread before entering
5. **Correlation check:** Don't stack correlated bets (e.g., multiple BTC markets = same exposure)

---

### Portfolio-Level Risk Management

| Limit | Recommended | Our Current |
|-------|------------|-------------|
| Max per position | 15% bankroll | 50% (❌ too high) |
| Max total exposure | 90% bankroll | Unknown |
| Daily stop-loss | 20% of portfolio | None (❌) |
| Max drawdown | 50% → halt trading | None |

---

### Systematic Biases to Exploit

**1. Longshot Bias (HIGH PRIORITY)**
- Retail systematically overpays for low-probability outcomes ($0.01-$0.20)
- Professionals exploit by: SELLING tails, BUYING favorites
- Our current DEEP_BUY strategy (<$0.15) is fighting against this edge

**2. Recency Bias / Mean Reversion**
- Prices overreact to recent news, then revert
- Short-term negative autocorrelation
- Strategy: Buy dips after overreaction, sell rallies

**3. Cross-Platform Arbitrage**
- Polymarket vs Kalshi price differences persist
- Example: PM YES $0.42 + Kalshi NO $0.56 = $0.98 cost → $1.00 payout = 2% arb
- Opportunities peak in final 2 weeks before events
- **We could implement this with PolyClaw + Kalshi API**

**4. Volume Inefficiency**
- High-volume national markets MORE inefficient than local/state markets
- Attention-driven mispricing overwhelms information aggregation
- Opportunity: Focus on underfollowed niche markets

---

### What Our Current Bots Are Missing

| Feature | Current Superbot | Recommended |
|---------|----------------|-------------|
| AI probability estimation | No | Claude/Gemini ensemble |
| Dynamic re-sizing | Fixed Kelly cap | Re-run Kelly on 10%+ price moves |
| Cooldown rules | No | 2-cycle cooldown after close |
| Confidence filtering | No | Skip if std dev > 10% |
| Edge-gone exit | No | Sell if market passes your estimate |
| Portfolio-level stop-loss | No | 20% daily stop, 50% max drawdown |
| Correlation sizing | No | Reduce when stacking correlated bets |
| Cross-platform arb | No | Polymarket ↔ Kalshi spread monitoring |
| Sell tails strategy | Buying deep Yes | Selling tail events (short OTM) |

---

### Kalshi Fee Calculator

Kalshi fees: `ceil(0.07 × contracts × price × (1-price))`
- Ranges ~0.6% (tail events) to 1.75% (mid-market $0.50)
- Maker rebate: up to 0.44% back

**Net EV after fees:**
```
Net EV = (p × $1) - Market_Price - Fee
```
Always factor fees into Kelly calculation for small-edge trades.

---

## 🧮 TRADING FORMULAS & STRATEGIES

### Current Active Strategies (Superbot)
1. **DEEP_BUY**: YES < $0.15 → buy cheap, ride to expiry
2. **DRIFT_BUY**: YES $0.35-$0.45 → mean reversion bounce
3. **DRIFT_SHORT**: YES $0.55-$0.65 → sell overpriced

### Strategy Rules
- DRIFT TP: +25%, SL: -15%
- DEEP: No stop loss, ride to expiry
- Kelly Criterion sizing (capped at 50%, $2 min/$2 max)

### Kelly Criterion Formula
```
f* = (bp - 1) / b  [where p = win prob, b = decimal odds]
```

---

## 🤖 OPENCLAW & BOT ARCHITECTURE

### Key Paths
- Superbot: `/home/ubuntu/.openclaw/workspace/workers/superbot/`
- Flip: `/home/ubuntu/.openclaw/workspace/workers/flip/`
- Thermostat: `/home/ubuntu/.openclaw/workspace/workers/thermostat/`
- Recorder: `/home/ubuntu/.openclaw/workspace/workers/recorder/`
- Uncle Vito: `/home/ubuntu/.openclaw/workspace/workers/uncle_vito/`

### Discord Webhook
- `https://discord.com/api/webhooks/1486066262122430684/...`

---

## 📝 RESEARCH LOG

_(Nerd's ongoing findings go here)_

### Technical Indicators (Needed)
- RSI (Relative Strength Index)
- MACD (Moving Average Convergence Divergence)
- Cointegration filters

---

## 🔥 MARKET INTEL (From @w1nklerr X Posts — March-April 2026)

### Account Overview
- @w1nklerr (winkle.) — Documents AI agent trading bot builds
- Focus: Claude + OpenClaw + Polymarket/Kalshi prediction markets
- Pattern: Leaked GitHub scripts + Claude = profitable trading bots

### Key Results Documented

| Date | Claimed Profit | Strategy | Win Rate |
|------|---------------|----------|----------|
| Apr 1 | $50,197 (from $100) | Claude + leaked GitHub | ~70% |
| Apr 1 | $30,103 | Liquidity Sniper terminal | - |
| Mar 31 | $45,401 (from $1,000) | GitHub + Claude | 79% |
| Mar 31 | $15,300 | Claude script (7hr build) | 69% |
| Mar 30 | $56,551 | Claude script formulas | - |
| Mar 30 | $1M | Google's algorithm in script | - |
| Mar 29 | $22,301 | Google quant paper → Claude | - |
| Mar 28 | $73K | Claude bot (NBA markets) | 73% |
| Mar 26 | $14,103 | OpenClaw agent | 70% |
| Mar 25 | $12K/week | 3 automated bots | 68% |
| Mar 24 | $40K | OpenClaw agent | 71% |
| Mar 24 | $1,000/day | Claude setup (overnight) | 72% |

### Recurring Patterns
1. **Build time**: 4-12 hours to write the script
2. **First night profit**: $4,000-$5,300 typical
3. **Win rates**: 68-79% reported
4. **Markets**: NBA game winners most common, also crypto, Polymarket
5. **Copytrading**: Following other wallets is a common strategy

### Core Strategy Template (from w1nklerr)
> "The system builds automated workflows for trading by turning domain expertise into structured skills that activate under specific conditions"

### What This Means for Yonti
- ✅ **CONFIRMED**: OpenClaw CAN generate profitable trading bots
- ✅ Our approach (CSO/Pixel/Nerd/Searcher) mirrors this pattern
- ✅ 68-77% win rates are achievable on NBA/prediction markets
- ⚠️ Most successful strategies use NBA markets — consider flipping to focus here
- ⚠️ Copytrading wallets is a shortcut — we could integrate this
- ⚠️ "Leaked GitHub files" suggest existing scripts we could study

### OpenClaw-Specific Mentions
- Mar 26: "OpenClaw made him $14,103 in one night" — script written in 10 hours
- Mar 24: "This OpenClaw agent made $40K profit" — no insider MCPs/plugins
- Both claim 70-71% win rates

### Copytrade Addresses Mentioned
- `0x...` Ethereum addresses shared for copy trading
- These show what wallets to follow for signal copying

### Source
- @w1nklerr on X | winkle. | ~39.8K followers
- Collected via Apify X Scraper on 2026-04-02

---

## 🏛️ POLYMARKET

### Overview
- **Type:** Decentralized prediction market (on Polygon blockchain)
- **Size:** World's largest prediction market by volume
- **Regulation:** Polymarket US (US users) requires KYC via iOS/Android app
- **Fees:** Variable, spreads built into markets

### API Access
- **Docs:** https://docs.polymarket.us (US) / https://docs.polymarket.com (International)
- **SDKs:** Python (`pip install polymarket-us`), TypeScript (`npm install polymarket-us`)
- **Setup:** Download app, verify identity, get API keys at polymarket.us/developer
- **Key ID + Secret Key** authentication

### Polymarket Python Example
```python
from polymarket_us import PolymarketUS
client = PolymarketUS(
    key_id=os.environ["POLYMARKET_KEY_ID"],
    secret_key=os.environ["POLYMARKET_SECRET_KEY"],
)
# Fetch markets (public, no auth)
events = client.events.list({"limit": 10, "active": True})
market = client.markets.retrieve_by_slug("chiefs-super-bowl")
book = client.markets.book("chiefs-super-bowl")
# Place order (auth required)
order = client.orders.create({
    "marketSlug": "chiefs-super-bowl",
    "intent": "ORDER_INTENT_BUY_LONG",
    "type": "ORDER_TYPE_LIMIT",
    "price": {"value": "0.55", "currency": "USD"},
    "quantity": 100,
    "tif": "TIME_IN_FORCE_GOOD_TILL_CANCEL",
})
```

### Key Differences from Kalshi
| Feature | Polymarket | Kalshi |
|---------|-----------|--------|
| Blockchain | Polygon (ETH L2) | Centralized |
| Regulation | Grey market (US) | CFTC regulated (US) |
| Markets | Crypto-native, higher volume | Traditional events |
| API | REST + WebSocket | REST only |
| Fees | Built into spread | 1.6% on winnings |

### Status for Yonti
- ❌ NOT YET INTEGRATED
- ✅ API access available once Tony sets up account + KYC
- ⚠️ US users need app download + identity verification
- Opportunity: Higher volume = better liquidity for NBA/sports markets

---

## 🔌 OPENCLAW INTEGRATION: Polymarket & Kalshi

### Option 1: PolyClaw (OpenClaw Skill for Polymarket)
**Source:** github.com/chainstacklabs/polyclaw | Available on ClawHub
**What it does:** Gives OpenClaw native tools to trade Polymarket

**Tools provided:**
- `polyclaw markets trending` — Top markets by 24h volume
- `polyclaw markets search "query"` — Search markets by keyword
- `polyclaw market` — Market details with prices
- `polyclaw buy YES/NO` — Execute trades via split + CLOB
- `polyclaw positions` — List open positions with live P&L
- `polyclaw wallet status` — Show address, POL/USDC.e balances
- `polyclaw hedge scan` — LLM-powered hedging opportunities

**Setup Requirements:**
1. **Chainstack node** — Sign up at console.chainstack.com (free tier available)
   - Need Polygon mainnet RPC URL
2. **Polygon wallet** — Private key with USDC for trading
3. **OpenRouter API key** — For LLM analysis (sk-or-v1-...)

**Install:**
```bash
clawhub install polyclaw --force
cd ~/.openclaw/skills/polyclaw
uv sync
```

**Config (openclaw.json → skills.entries.polyclaw.env):**
```json
"polyclaw": {
  "enabled": true,
  "env": {
    "CHAINSTACK_NODE": "https://polygon-mainnet.core.chainstack.com/YOUR_KEY",
    "POLYCLAW_PRIVATE_KEY": "0x...",
    "OPENROUTER_API_KEY": "sk-or-v1-..."
  }
}
```

**Before first trade (one-time approval):**
```bash
uv run python scripts/polyclaw.py wallet approve
```

---

### Option 2: Clawmarket (MCP Server for Polymarket + Kalshi)
**Source:** docs.useclawmarket.com
**What it does:** MCP server connecting OpenClaw to BOTH Polymarket AND Kalshi
**Status:** ⚠️ Setup instructions not fully accessible — docs site was blocked

Clawmarket exposes both Polymarket and Kalshi as callable MCP tools:
- Market data from both platforms
- Order execution
- Position tracking
- Settlement verification

---

### Recommendation for Yonti

**Start with PolyClaw (simpler):**
1. Tony signs up for Chainstack (free) → get Polygon RPC
2. Tony creates/has Polygon wallet with USDC → get private key
3. Tony gets OpenRouter API key (or we use existing)
4. Pixel installs + configures polyclaw skill

**Then expand to Clawmarket** if we want unified Kalshi + Polymarket access.

**Note:** Polymarket trading requires real funds on Polygon. Paper trading not available — actual USDC needed.

---

## ⚖️ OPENLAW

### Overview
- **Type:** Blockchain-based legal agreement platform (NOT a prediction market)
- **Company:** ConsenSys spinoff, launched 2017
- **Purpose:** Smart legal contracts — model legal agreements using code
- **Blockchain:** Ethereum-based
- **Partners:** Thomson Reuters, Rocket Lawyer, Chainlink

### What OpenLaw Does
- Digital signing of legal agreements
- Tokenization of assets
- On-chain smart contract management
- Integration framework for enterprise legal work

### OpenLaw vs Prediction Markets
OpenLaw is **NOT** a prediction market — it's legal infrastructure for:
- Creating binding legal agreements on blockchain
- Smart contracts with legal enforceability
- Reducing friction in legal transactions

### Status for Yonti
- ❌ NOT RELEVANT for current trading ops
- May become relevant if we tokenize trading stakes or create legal wrappers for fund management

---

## ⚖️ KALSHI (Existing Integration)

### API Details
- **Base URL:** `https://api.elections.kalshi.com/trade-api/v2/`
- **Auth Header:** `KALSHI-ACCESS-KEY: 0ebe781e-ce07-4e19-98eb-0d2d8e0ea20b`
- **Markets:** Crypto 15-min, NBA game winners, NHL, climate, economic
- **Fee:** 1.6% on winnings

### Active Series for Our Bots
- Crypto 15-min: `KXBTC15M`, `KXETH15M`, `KXSOL15M`, `KXXRP15M`, `KXDOGE15M`, `KXBNB15M`, `KXHYPE15M`, `KXADA15M`
- NBA: `KXNBAGAME`
- NHL: `KXNHLGAME`

### Known Limitations
- Sports API returns PRE-GAME odds only (no live in-game data via API)
- Live odds only visible on website
- Need websocket or alternative source for live sports pricing

---

## 🔧 GAPS & TODO

- [ ] Polymarket integration (needs Tony to set up account + KYC)
- [ ] Coinbase CLOB for order book data
- [ ] Live sports odds via websocket (Kalshi limitation)
- [ ] RSI/MACD indicators in strategies.py
- [ ] Test NBA game winner markets on Kalshi vs Polymarket liquidity

---

_Last updated: 2026-04-02 06:47 EST (Tony research)_
