# Polymarket Poller — GitHub Actions Setup

## Overview

This workflow (`.github/workflows/polymarket_poller.yml`) polls the Polymarket CLOB API every 5 minutes and:

1. Fetches active BTC / crypto 5-min markets
2. Saves results to `workers/data/live_markets.json` (auto-commits to the repo)
3. Posts an embed summary to Discord via webhook

---

## Required GitHub Secrets

Add these to your GitHub repo under **Settings → Secrets and variables → Actions**:

| Secret Name | Value |
|---|---|
| `POLYMARKET_API_KEY` | Your Polymarket API key (Bearer token) — get from `workers/config.json` → `polymarket_api_key` |
| `DISCORD_WEBHOOK` | Your Discord webhook URL — get from `workers/config.json` → `discord_webhook` |

### Example values (from config):

- **`POLYMARKET_API_KEY`**: `5f733fe2-5439-94c5-696b-1666202653f8`
- **`DISCORD_WEBHOOK`**: `https://discord.com/api/webhooks/1486066262122430684/mLKWVlGJRyADWEnpDgx3n4QcI1B-JhAnDLyBHKwsK-BSmeo5lal5MYrrY_QiuOBqiNLy`

---

## How to Add Secrets

1. Go to your GitHub repo: `https://github.com/<owner>/<repo>/settings/secrets/actions`
2. Click **"New repository secret"** for each secret above
3. Paste the name and value, then click **Add secret**

---

## Workflow Behavior

- **Schedule:** Every 5 minutes (`*/5 * * * *`)
- **Manual trigger:** Available via **Actions → Polymarket Poller → Run workflow**
- **Rate limit handling:** Retries up to 3x with exponential backoff on 429 responses
- **Heartbeat:** If the API fails or returns empty data, a minimal heartbeat message is still posted to Discord so you know the workflow ran

---

## Files

| File | Purpose |
|---|---|
| `.github/workflows/polymarket_poller.yml` | The GitHub Actions workflow |
| `workers/data/live_markets.json` | Auto-updated market data (committed on each run) |
| `.github/README.md` | This file |
