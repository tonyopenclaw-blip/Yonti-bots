# Superbot Trade Analysis - 2026-04-06

## Current Status
- **Session**: 19:35:29 - 19:39:34 UTC (~4 min run)
- **Balance**: $34.67 → $45.65 (ending)
- **Realized P&L**: -$0.205
- **Open Positions**: 3 (ETH, BNB, XRP momentum - all underwater)
- **Cash**: ~$7.31

---

## Completed Trades (from report.json)

| # | Ticker | Strategy | Side | Entry | Exit | PnL | Hold Time | Exit Reason |
|---|--------|----------|------|-------|------|-----|------------|-------------|
| 1 | XRP | first_cross | yes | $0.325 | $0.255 | -$0.98 | ~2 min | TRAILING STOP |
| 2 | ETH | momentum | yes | $0.50 | $0.50 | -$0.105 | ~2 min | shutdown |
| 3 | BNB | momentum | yes | $0.55 | $0.50 | -$0.10 | ~2 min | shutdown |
| 4 | XRP | momentum | yes | $0.255 | $0.50 | +$0.98 | 31 sec | shutdown |

---

## Earlier Session Trades (17:37-17:52)

| # | Ticker | Strategy | Side | Entry | Exit | PnL | Hold Time |
|---|--------|----------|------|-------|------|-----|------------|
| 5 | ETH | first_cross | no | $0.365 | $0.0025 | -$0.36 | ~5.5 min |
| 6 | BNB | first_cross | no | $0.360 | $0.08 | -$0.28 | ~5.5 min |
| 7 | SOL | momentum | yes | $0.625 | $0.0105 | -$0.61 | ~5.5 min |

**Abandoned positions** (bot crashed/restarted while BTC, SOL, DOGE first_cross were open)

---

## Performance Metrics

### Win Rate by Strategy
| Strategy | Trades | Wins | Losses | Win Rate |
|----------|--------|------|--------|----------|
| **first_cross** | 2 | 0 | 2 | 0% |
| **momentum** | 2 | 1 | 1 | 50% |
| **TOTAL** | 4 | 1 | 3 | **25%** |

### Win Rate by Coin
| Coin | Trades | Wins | Losses | Win Rate |
|------|--------|------|--------|----------|
| XRP | 2 | 1 | 1 | 50% |
| ETH | 1 | 0 | 1 | 0% |
| BNB | 1 | 0 | 1 | 0% |

---

## Hold Time Analysis

- **Winners**: The XRP momentum winner was held only **31 seconds** before shutdown - didn't run to expiry
- **Losers**: ETH, BNB, SOL all held near full duration (~5.5 min) and went to zero
- **Pattern**: Winners cut early (shutdown), losers go to zero (run to expiry)

---

## Critical Issues

### 🔴 CRITICAL: Bot Instability
1. **API Errors**: 400 Bad Request, 401 Unauthorized repeating every 5 seconds
2. **SDK Bug**: `'Market' object has no attribute 'time_to_expiry_sec'` - crash loop
3. **Multiple restarts**: Bot crashed/restarted 4+ times in 20 minutes
4. **Positions abandoned**: BTC, SOL, DOGE first_cross positions left open during crash

### 🔴 CRITICAL: Trailing Stop Too Tight
- XRP first_cross was stopped out at $0.255 (entry $0.325) for a 21.5% loss
- Trailing stop of 50%/40% triggered too early in sideways action

### 🟡 WARNING: Scale-In Problem
- Bot scaled into ETH/BNB positions at worse prices (buying more as price dropped)
- This increased losses on losing trades
- Scale-in at $0.24, $0.165 for ETH (avg $0.365)

### 🟡 WARNING: Cash Desync
- Internal cash ($34.67) vs real balance ($7.31) completely desynced
- Sizing algorithm thinks there's more money than reality

---

## 5 Recommendations for Next Cycle

### 1. 🔧 FIX THE CRASH LOOP FIRST
The `time_to_expiry_sec` AttributeError is crashing the bot every loop. Pixel needs to:
- Check if method exists before calling it
- Add try/except around market time checks
- This is BLOCKING all trading

### 2. 🔧 FIX API AUTHENTICATION
- 401 errors mean Kalshi API credentials are failing
- Check if KALSHI_API_KEY_ID / KALSHI_SECRET_KEY are set correctly
- This is causing position desync and inability to close positions

### 3. 📊 RELAX TRAILING STOP for first_cross
- Current: 50%/40% - too tight for 15-min binary options
- Recommend: 70%/60% or disable entirely for first_cross
- The XRP trade had potential but got stopped out early

### 4. 🚫 DISABLE SCALE-IN (or fix it)
- Scale-in is averaging into losing positions
- Either disable completely or only scale into winning positions
- Better: add max_scale_ins = 1 (no double-down)

### 5. 💰 FIX CASH SYNC
- Real balance is ~$7 but bot thinks ~$35
- Kelly calculator will oversize bets
- Force cash sync on startup before trading begins

---

## Summary
- **Win Rate**: 25% (1/4 trades)
- **Total P&L**: -$0.205 realized
- **Biggest Winner**: +$0.98 (XRP momentum)
- **Biggest Loser**: -$0.98 (XRP first_cross)
- **Unrealized Loss**: ~$1.43 (3 open positions)
- **Bot Health**: CRITICAL - crashing/recovering

**Bottom line**: The strategy is generating signals but the bot is too unstable to execute properly. Fix the crashes first, then optimize the strategy.
