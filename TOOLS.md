# TOOLS.md - Local Notes

Skills define _how_ tools work. This file is for _your_ specifics — the stuff that's unique to your setup.

## What Goes Here

Things like:

- Camera names and locations
- SSH hosts and aliases
- Preferred voices for TTS
- Speaker/room names
- Device nicknames
- Anything environment-specific

## Examples

```markdown
### Cameras

- living-room → Main area, 180° wide angle
- front-door → Entrance, motion-triggered

### SSH

- home-server → 192.168.1.100, user: admin

### TTS

- Preferred voice: "Nova" (warm, slightly British)
- Default speaker: Kitchen HomePod

### Apify (Twitter/X Scraper)

- API Key: `apify_api_sK4vzx6r1hzexr7TA2muKebeQWqChT2psmmB`
- Actor: `xtdata/twitter-x-scraper`
- Account: Tbruno94 (free tier, $5/month credit)
- Cost: $0.0005/start + $0.005/tweet
- Usage: Scrapes tweets by URL or search terms
- Free tier proxy groups available (BUYPROXIES94952 - 5 proxies)

### Twitter/X API (Official - DEPLETED)

- Account ID: 2039639853785071616
- Status: 402 Credits Depleted
- Uses: Posting tweets, future read access when credits refilled

### X/Twitter Sharp Bettor Accounts (for Vito weighting)

- dangambleai
- codybrownbets
- harrylockpicks
- cookitup31

### Odds API Keys (The Odds API - oddsapi.io)

Rotate between these 3 keys. Use `ebfae5a368a75fb6f9e971b9686da2f7` (0/500 - fresh) first:

1. `5b62457b1049c4e92541d10b53b64aa3` - 232/500 used
2. `cb42c4fe578ae32bbaf58923493d26e5` - 499/500 used (NEARLY DEPLETED - use last)
3. `ebfae5a368a75fb6f9e971b9686da2f7` - 0/500 used (FRESH - prefer this)
```

## Why Separate?

Skills are shared. Your setup is yours. Keeping them apart means you can update skills without losing your notes, and share skills without leaking your infrastructure.

---

## Kalshi API Keys

| Bot | Access Key ID | Type | Notes |
|-----|-------------|------|-------|
| **Real Superbot 3** (active) | `a0235926-8b18-4f93-81ab-e4383ba61ec9` | R/W | Current trading bot |
| Cashsync | `12920c50-132b-4237-9575-7d5958a74830` | R/W | Used by CashSync |
| Real Superbot 2 | `f085af89-0df7-44e2-9bb3-4af0435cbfda` | R/W | Backup |
| RealSuperbot | `e275fa0a-90e0-4eaa-9fb1-d25c9f8ed804` | R/W | Backup |
| Thermostat | `c5187b0e-785e-4749-b45b-70f9cd40bb0f` | R/W | Climate bot |
| Flip | `e42b9849-e6e3-484e-b17c-48a078f38642` | R/W | NBA flip bot |
| First cross tracker | `dd143eb9-ac4a-4cc2-bb17-11b47147a8fe` | Read only | Research only |
| Recorder | `7528928b-a38e-46f2-906f-ccfa61743ad0` | R/W | Price recorder |

**Private key file:** `/home/ubuntu/.openclaw/workspace/workers/superbot/kalshi_private_key.pem`

---

Add whatever helps you do your job. This is your cheat sheet.
