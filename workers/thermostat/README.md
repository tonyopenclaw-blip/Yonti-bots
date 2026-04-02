# Thermostat - Weather Forecast Arbitrage Bot

Weather forecast arbitrage bot for Kalshi climate markets.

## Strategy

1. **Fetch NOAA/NWS forecasts** for key US cities (NYC, LA, Chicago, Houston, Phoenix, etc.)
2. **Poll Kalshi climate markets** (KXCLIMATE series) for temperature-based binary markets
3. **Compare NOAA projections vs market lines** - e.g., if NOAA says "high of 82°F" and market is "over/under 80°F"
4. **Bet with edge**: Buy OVER if NOAA projects above threshold, buy UNDER if below
5. **Paper trading only**: $100 starting balance, $2 max bet

## File Structure

```
thermostat/
├── config.py          # Configuration (cities, API endpoints, limits)
├── kalshi_api.py      # Copied from superbot, extended for climate series
├── thermostat.py      # Main bot: NOAA client, market parser, paper ledger
├── run.sh             # Shell script to launch the bot
├── data/
│   ├── thermostat_trades.json   # All trade records
│   └── thermostat_stats.json    # Running statistics
└── logs/
    └── thermostat.log           # Bot log
```

## Key Components

### NOAAClient
- Fetches 7-day forecasts from NWS API (`api.weather.gov`)
- Caches forecasts for 30 minutes
- Extracts daily high/low temperatures

### ClimateMarketParser
- Parses Kalshi question text to extract city, threshold, direction
- Supports patterns like:
  - "Will the high temperature in NYC exceed 75°F?"
  - "Will the high temperature in LA be under 80°F?"

### PaperLedger
- Tracks $100 paper balance
- Records all trades with PnL
- Auto-saves to JSON files

### ThermostatBot
- Main loop: fetch forecasts → scan markets → place bets → check positions
- 1-hour poll interval

## Weather Data Saved

Every trade saves:
- City and forecast high temperature
- Market threshold and direction
- Edge (forecast - threshold)
- NOAA data for future backtesting

## Running

```bash
cd /home/ubuntu/.openclaw/workspace/workers/thermostat
./run.sh
```

Or directly:
```bash
python3 thermostat.py
```

## Notes

- Paper trading only (no real money)
- 10 US cities tracked: NYC, LA, Chicago, Houston, Phoenix, Philadelphia, San Antonio, San Diego, Denver, Atlanta
- Bot gracefully handles API errors and missing data
- Logs everything to `logs/thermostat.log`
