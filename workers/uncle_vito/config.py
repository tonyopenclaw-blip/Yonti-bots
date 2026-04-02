"""
Uncle Vito's Betting Report - Configuration
🍝 Sports betting report generator for Yonti
"""

from dataclasses import dataclass
from typing import List

# ESPN API endpoints
ESPN_API_BASE = "https://site.api.espn.com/apis/site/v2"

SPREDSHEET_API = {
    "nba": f"{ESPN_API_BASE}/sports/basketball/nba/scoreboard",
    "nhl": f"{ESPN_API_BASE}/sports/hockey/nhl/scoreboard",
    "ncaab": f"{ESPN_API_BASE}/sports/basketball/mens-college-basketball/scoreboard",
}

# Sports covered
SPORTS = ["NBA", "NHL", "NCAAB"]

# Parlay settings
PARLAY_LEGS = 4

# Source signals for picking direction/confidence
# These represent betting source signals we reference
SOURCES = {
    "dans_ai": {"name": "Dans AI", "weight": 0.30, "confidence_boost": 5},
    "cody_brown": {"name": "Cody Brown Bets", "weight": 0.25, "confidence_boost": 3},
    "chef_t": {"name": "Chef T", "weight": 0.25, "confidence_boost": 4},
    "harry_lock": {"name": "Harry Lock Picks", "weight": 0.20, "confidence_boost": 3},
}

# Default odds for props (when not available from API)
DEFAULT_PROP_ODDS = -110  # Standard -110 juice

# Moneyline defaults by sport
DEFAULT_ML_ODDS = {
    "nba": {"favorite": -150, "underdog": +130},
    "nhl": {"favorite": -140, "underdog": +120},
    "ncaab": {"favorite": -160, "underdog": +140},
}

# Prop stat categories
PROP_STATS = {
    "basketball": ["points", "rebounds", "assists", "threes", "blocks", "steals"],
    "hockey": ["goals", "assists", "shots_on_goal", "saves"],
}

# Report output channel (Discord channel ID or name)
DEFAULT_DISCORD_CHANNEL = "uncle-vito"

# Hit rate tracking (would connect to historical data)
HISTORICAL_HIT_RATES = {
    "props": 0.58,  # 58% historical props hit rate
    "winners": 0.63,  # 63% historical winners hit rate
}

# Date format
DATE_FORMAT = "%m/%d/%Y"
TIME_FORMAT = "%I:%M %p ET"

# The Odds API (the-odds-api.com) - DK + FD for NBA/NHL/NCAAB
# Free tier: 500 credits/month
ODDS_API_KEY = "cb42c4fe578ae32bbaf58923493d26e5"  # The Odds API - DK + FD
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
ODDS_REGIONS = "us"  # Covers DraftKings, FanDuel
ODDS_SPORTS = {
    "nba": "basketball_nba",
    "nhl": "icehockey_nhl",
    "ncaab": "basketball_ncaab",
}
# Alternative: sportsbook-odds-scraper (GitHub: declanwalpole/sportsbook-odds-scraper)
