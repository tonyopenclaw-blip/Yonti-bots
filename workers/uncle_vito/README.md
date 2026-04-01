# 🍝 Uncle Vito's Betting Report

Sports betting report generator for Yonti.

## Overview

Generates daily betting reports with:
- **4-Leg Props Parlay** (player over/under props)
- **4-Leg Winners Parlay** (game winners)

## Usage

```bash
# Generate report to console
python vito_report.py

# Run with CLI options
python run.py --sport NBA

# Send to Discord
python run.py --discord --channel uncle-vito
```

## Files

- `config.py` - Configuration (ESPN API, sources, odds)
- `vito_report.py` - Main report generator
- `run.py` - CLI interface
- `__init__.py` - Module init

## Data Sources

- **ESPN API** - Game schedules and scores
- **Source Signals** - Dans AI, Cody Brown Bets, Chef T, Harry Lock Picks (simulated)

## Notes

Props are simulated since ESPN doesn't provide prop lines via their free API.
Winners are generated using source signal aggregation with spread/moneyline logic.

⚠️ This is for entertainment purposes. Always do your own research.
