# DK & FD Sports Betting Odds Data Sources

**Research by:** Nerd (Yonti Research Division)
**Date:** 2026-04-01
**Focus:** NBA, NHL, NCAAB odds data from DraftKings and FanDuel

---

## TL;DR — Top Recommendation

**The Odds API** (the-odds-api.com) is the best all-around option. It covers both DraftKings and FanDuel, includes NBA/NHL/NCAAB, has a free tier, and has official GitHub support. Read on for details and alternatives.

---

## 1. The Odds API ⭐ RECOMMENDED

**Website:** https://the-odds-api.com/
**GitHub:** https://github.com/the-odds-api (official)
**Sample Code:** https://github.com/the-odds-api/samples-python

### What It Provides
- Real-time and pre-match betting odds from 40+ bookmakers worldwide
- US bookmakers include: **DraftKings, FanDuel, BetMGM, Caesars, Bovada, MyBookie.ag**
- Sports covered: **NBA, NCAAB, NHL**, NFL, MLB, WNBA, soccer, golf, tennis, etc.
- Markets: Moneyline (h2h), spreads, totals (over/under), futures/outrights, player props
- Historical odds snapshots available (back to 2020)
- JSON format; decimal or American odds format

### How to Access
- API key required (free email registration)
- REST API: `https://api.the-odds-api.com/v4/sports/{sport}/odds/`
- Free tier: **500 credits/month**
- Paid plans: $30/month (20K credits), $59/month (100K), $119/month (5M), $249/month (15M)
- Each region+market combo costs 1 credit per request
- Example: NBA (1 sport) + 1 region (us) + 3 markets (h2h, spreads, totals) = 3 credits/call
- Response headers show remaining credits (`x-requests-remaining`)

### Free Tier Assessment
- 500 credits/month is enough for ~165 API calls at 3 credits each (or ~500 calls at 1 credit each)
- Sufficient for periodic report generation (not high-frequency polling)
- Requires no scraping, no ToS violation concerns

### NBA/NHL/NCAAB Specifics
- Sport keys: `basketball_nba`, `icehockey_nhl`, `basketball_ncaab`
- US region (`regions=us`) covers DK and FD among others
- Spreads and totals primarily available for US sports

---

## 2. sportsbook-odds-scraper

**GitHub:** https://github.com/declanwalpole/sportsbook-odds-scraper
**Language:** Python
**License:** Not specified (MIT likely)

### What It Provides
- Scrapes **DraftKings, FanDuel, BetMGM, Caesars, BetRivers/Sugarhouse, Superbook, Bovada**
- Also Australian books: SportsBet, TAB, Ladbrokes, PointsBet
- Returns ALL markets and odds in a **normalized pandas DataFrame**
- Can write to CSV
- Includes GUI app (`python app.py`)
- Supports in-play (live) and pregame scraping

### How to Access
- **No API key needed** — scrapes via sportsbooks' undocumented internal APIs
- Takes a match URL as input (e.g., `https://sportsbook.draftkings.com/event/...`)
- Can be run in a loop to track odds over time
- No SLA — sportsbooks can change/block at any time
- No rate limiting built-in (be respectful)

### Free Tier Assessment
- Completely free and open source
- Risk: sportsbooks may block IP or change API without notice
- Best for research/data collection, not production reliability

### NBA/NHL/NCAAB Specifics
- Works for any sport — NBA, NHL, NCAAB all supported
- Just need the correct DraftKings event URL for the game
- Example uses include tracking odds fluctuation over game duration

---

## 3. Draft-Kings-Odds-Scraper

**GitHub:** https://github.com/Davidboy1014/Draft-Kings-Odds-Scraper
**Language:** Python

### What It Provides
- Python scraper for DraftKings betting odds
- Supports: **MLB, NBA, NFL, NHL**
- Market types: Spreads, totals, moneylines, player props
- Outputs: JSON and CSV
- Modular structure — separate modules per sport

### How to Access
- **API endpoints have been removed from the repo** for legal/safety reasons
- Users must provide their own DraftKings API endpoints
- No authentication required for public data (uses public endpoints)
- Includes rate limiting and proper user-agent headers

### Free Tier Assessment
- Free if you can source working DK endpoints
- Endpoints may break as DK changes their API

---

## 4. FanDuel API (Setfive)

**GitHub:** https://github.com/Setfive/fanduel-api
**Language:** TypeScript / Node.js

### What It Provides
- TypeScript library for FanDuel DFS (Daily Fantasy Sports) — NOT sportsbook
- Accesses FanDuel.com's internal REST endpoints
- Features: get available slates, player data, WebSocket streaming for lobby updates
- Includes a brute-force lineup generator example

### How to Access
- Requires **FanDuel username and password** (credentials)
- Explicitly against FanDuel ToS — use at your own risk
- No API key — uses user credentials for auth
- WebSocket support for live data

### ⚠️ Warning
- **This is for DFS (fantasy), not sportsbook betting odds**
- Against FanDuel Terms of Service
- Not useful for sportsbook odds comparison

---

## 5. DraftKings API Documentation (Unofficial)

**GitHub:** https://github.com/SeanDrum/Draft-Kings-API-Documentation

### What It Provides
- Unofficial reverse-engineered docs for DraftKings internal API
- Covers: Draft Groups, Draftables (players + salaries), Contests, Game Types
- Endpoints: `https://api.draftkings.com/...`
- DFS-focused (not sportsbook odds)

### How to Access
- Completely open, no auth
- DraftKings does NOT intend for public API use
- No SLA — can break at any time with DK API updates
- ⚠️ DFS-focused, not sportsbook betting odds

---

## 6. Pinnacle API (Bonus — Industry Standard)

**Website:** https://www.pinnacle.com/
**Note:** Not DK or FD, but worth knowing for benchmarking

### What It Provides
- Free API for account holders
- Considered the **sharpest market lines** — pro bettors use Pinnacle as the benchmark
- Covers: NFL, NBA, NHL, MLB, soccer, etc.
- Pre-game, live, and closing line odds

### How to Access
- Requires having a Pinnacle betting account
- Free but only covers Pinnacle's own odds
- Often used alongside DK/FD data to compare market efficiency

### Free Tier Assessment
- Free for Pinnacle customers
- Excellent for benchmarking — if DK/FD odds differ significantly from Pinnacle, there's potential value

---

## 7. SportsGamesOdds (Aggregated)

**Website:** https://sportsgameodds.com/
**Aggregator for:** DraftKings, FanDuel, BetMGM, Caesars + 35+ others

### What It Provides
- WebSocket streaming for live odds
- Player props, Same Game Parlays (SGP)
- 40+ US sportsbooks in one integration

### Pricing
- From **$29/month**

### Notes
- Worth evaluating alongside The Odds API for comparison
- WebSocket support useful for real-time betting applications

---

## Summary Table

| Source | DK | FD | NBA | NHL | NCAAB | Free? | API Key | Reliability |
|--------|----|----|-----|-----|-------|-------|---------|-------------|
| **The Odds API** | ✅ | ✅ | ✅ | ✅ | ✅ | 500/mo free | Yes | High (paid) |
| **sportsbook-odds-scraper** | ✅ | ✅ | ✅ | ✅ | ✅ | Yes | No | Medium (no SLA) |
| **DraftKings-Odds-Scraper** | ✅ | ❌ | ✅ | ✅ | ❌ | Yes | No* | Low (endpoints removed) |
| **Pinnacle API** | ❌ | ❌ | ✅ | ✅ | ✅ | Yes (w/account) | No | High |
| **FanDuel API (Setfive)** | ❌ | DFS only | ❌ | ❌ | ❌ | Yes | Credentials | Low (ToS violation) |

---

## Recommendation for Yonti's Betting Report

**Start with The Odds API** — free tier is sufficient for periodic report generation. Covers DK and FD for NBA, NHL, and NCAAB out of the box.

If The Odds API's free tier runs out or you need higher frequency:
- Consider the **sportsbook-odds-scraper** for raw DK/FD data collection
- Pinnacle API as a free benchmark to compare market efficiency

Avoid the FanDuel TypeScript library — it's DFS-focused, not sportsbook odds.

---

## Risks & Legal Notes

- DraftKings and FanDuel do **not** have public APIs for sportsbook odds
- Unofficial APIs/scrapers may violate ToS
- The Odds API is an aggregator that has arrangements with bookmakers — safest legal option
- Always respect rate limits and robots.txt when scraping
- Data is for research/analysis — comply with local laws
