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

## 🔧 GAPS & TODO

- [ ] Polymarket integration
- [ ] Coinbase CLOB for order book data
- [ ] Live sports odds via websocket
- [ ] RSI/MACD indicators in strategies.py
- [ ] 7+ simultaneous coins on Kalshi (currently only BTC tested fully)

---

_Last updated: 2026-04-02 05:23 EST (Tony)_
