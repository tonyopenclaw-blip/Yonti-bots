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
SPORTS = ["NBA", "NHL", "MLB"]

# Parlay settings
PARLAY_LEGS = 3

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
    "mlb": {"favorite": -160, "underdog": +140},
}

# Prop stat categories
PROP_STATS = {
    "basketball": ["points", "rebounds", "assists", "threes", "blocks", "steals"],
    "hockey": ["goals", "assists", "shots_on_goal", "saves"],
    "baseball": ["hits", "runs", "RBI", "home_runs", "strikeouts"],
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

# Discord webhook for Uncle Vito reports
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1486066262122430684/mLKWVlGJRyADWEnpDgx3n4QcI1B-JhAnDLyBHKwsK-BSmeo5lal5MYrrY_QiuOBqiNLy"

# The Odds API (the-odds-api.com) - DK + FD for NBA/NHL/NCAAB
# Free tier: 500 credits/month
ODDS_API_KEY = "5b62457b1049c4e92541d10b53b64aa3"  # The Odds API - DK + FD
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
ODDS_REGIONS = "us"  # Covers DraftKings, FanDuel
ODDS_SPORTS = {
    "nba": "basketball_nba",
    "nhl": "icehockey_nhl",
    "mlb": "baseball_mlb",
}
# Alternative: sportsbook-odds-scraper (GitHub: declanwalpole/sportsbook-odds-scraper)


# ============================================================
# STAR PLAYER AVERAGE STATS (for rest day adjustments)
# ============================================================
# When a star player is flagged OUT (not in DK DFS slate):
# - Remove them from props/parlays
# - Reduce their team's projected points by ~50% of their avg
# - Shift spread toward that team by ~5-8 points
# - Lower O/U total by 8-12 points
#
# Format: { "Player Name": { "pts": X, "reb": X, "ast": X, "team": "XXX" }, ... }
PLAYER_AVG_STATS = {
    # NBA Players
    "Tyrese Maxey": {"pts": 24, "reb": 4, "ast": 5, "team": "PHI"},
    "Paul George": {"pts": 20, "reb": 5, "ast": 4, "team": "PHI"},
    "Jordan Poole": {"pts": 20, "reb": 3, "ast": 4, "team": "WSH"},
    "Paolo Banchero": {"pts": 23, "reb": 6, "ast": 5, "team": "ORL"},
    "Franz Wagner": {"pts": 20, "reb": 5, "ast": 3, "team": "ORL"},
    "Trae Young": {"pts": 26, "reb": 3, "ast": 10, "team": "ATL"},
    "Jalen Johnson": {"pts": 16, "reb": 8, "ast": 4, "team": "ATL"},
    "Tyler Herro": {"pts": 22, "reb": 5, "ast": 4, "team": "MIA"},
    "Bam Adebayo": {"pts": 20, "reb": 10, "ast": 4, "team": "MIA"},
    "Jayson Tatum": {"pts": 27, "reb": 8, "ast": 4, "team": "BOS"},
    "Jaylen Brown": {"pts": 24, "reb": 6, "ast": 3, "team": "BOS"},
    "Jaren Jackson Jr.": {"pts": 20, "reb": 6, "ast": 2, "team": "MEM"},
    "Desmond Bane": {"pts": 20, "reb": 4, "ast": 3, "team": "MEM"},
    "Karl-Anthony Towns": {"pts": 24, "reb": 11, "ast": 3, "team": "NY"},
    "Jalen Brunson": {"pts": 25, "reb": 3, "ast": 6, "team": "NY"},
    "LeBron James": {"pts": 25, "reb": 7, "ast": 8, "team": "LAL"},
    "Luka Doncic": {"pts": 28, "reb": 8, "ast": 8, "team": "LAL"},
    "Nikola Jokic": {"pts": 26, "reb": 12, "ast": 9, "team": "DEN"},
    "Jamal Murray": {"pts": 22, "reb": 4, "ast": 5, "team": "DEN"},
    "Stephen Curry": {"pts": 29, "reb": 4, "ast": 6, "team": "GSW"},
    "Klay Thompson": {"pts": 18, "reb": 4, "ast": 2, "team": "GSW"},
    "Giannis Antetokounmpo": {"pts": 30, "reb": 11, "ast": 5, "team": "MIL"},
    "Damian Lillard": {"pts": 24, "reb": 4, "ast": 7, "team": "MIL"},
    "Kyrie Irving": {"pts": 25, "reb": 4, "ast": 5, "team": "DAL"},
    "Dereck Lively": {"pts": 10, "reb": 7, "ast": 1, "team": "DAL"},
    "Shai Gilgeous-Alexander": {"pts": 32, "reb": 5, "ast": 5, "team": "OKC"},
    "Jalen Williams": {"pts": 18, "reb": 4, "ast": 4, "team": "OKC"},
    "Donovan Mitchell": {"pts": 25, "reb": 5, "ast": 5, "team": "CLE"},
    "Darius Garland": {"pts": 20, "reb": 3, "ast": 7, "team": "CLE"},
    "Anthony Edwards": {"pts": 27, "reb": 5, "ast": 5, "team": "MIN"},
    "Julius Randle": {"pts": 22, "reb": 9, "ast": 4, "team": "MIN"},
    "Alperen Sengun": {"pts": 18, "reb": 9, "ast": 4, "team": "HOU"},
    "Fred VanVleet": {"pts": 17, "reb": 3, "ast": 7, "team": "HOU"},
    "Victor Wembanyama": {"pts": 22, "reb": 10, "ast": 3, "team": "SAS"},
    "Chris Paul": {"pts": 12, "reb": 4, "ast": 9, "team": "SAS"},
    "Kevin Durant": {"pts": 27, "reb": 6, "ast": 4, "team": "PHX"},
    "Devin Booker": {"pts": 26, "reb": 4, "ast": 5, "team": "PHX"},
    "Zion Williamson": {"pts": 23, "reb": 6, "ast": 3, "team": "NOP"},
    "CJ McCollum": {"pts": 21, "reb": 4, "ast": 4, "team": "NOP"},
    "De'Aaron Fox": {"pts": 25, "reb": 4, "ast": 5, "team": "SAC"},
    "Domantas Sabonis": {"pts": 19, "reb": 12, "ast": 6, "team": "SAC"},
    "Tyrese Haliburton": {"pts": 20, "reb": 4, "ast": 10, "team": "IND"},
    "Pascal Siakam": {"pts": 21, "reb": 6, "ast": 4, "team": "IND"},
    "Lauri Markkanen": {"pts": 21, "reb": 6, "ast": 2, "team": "UTAH"},
    "LaMelo Ball": {"pts": 24, "reb": 6, "ast": 8, "team": "CHA"},
    "Miles Bridges": {"pts": 19, "reb": 6, "ast": 3, "team": "CHA"},
    "Cameron Thomas": {"pts": 22, "reb": 3, "ast": 3, "team": "BKN"},
    "Cade Cunningham": {"pts": 23, "reb": 5, "ast": 7, "team": "DET"},
    "Jaden Ivey": {"pts": 18, "reb": 4, "ast": 4, "team": "DET"},
    "Scottie Barnes": {"pts": 20, "reb": 8, "ast": 5, "team": "TOR"},
    "RJ Barrett": {"pts": 20, "reb": 5, "ast": 3, "team": "TOR"},
    "Anfernee Simons": {"pts": 23, "reb": 3, "ast": 4, "team": "POR"},
    "Zach LaVine": {"pts": 25, "reb": 4, "ast": 4, "team": "CHI"},
    "Nikola Vucevic": {"pts": 18, "reb": 10, "ast": 3, "team": "CHI"},
    "Kawhi Leonard": {"pts": 24, "reb": 6, "ast": 3, "team": "LAC"},
    "James Harden": {"pts": 18, "reb": 5, "ast": 9, "team": "LAC"},
    # NHL Players
    "Connor McDavid": {"pts": 2, "goals": 0.5, "assists": 1.5, "team": "EDM"},
    "Leon Draisaitl": {"pts": 2, "goals": 0.5, "assists": 1, "team": "EDM"},
    "Nathan MacKinnon": {"pts": 2, "goals": 0.5, "assists": 1, "team": "COL"},
    "Auston Matthews": {"pts": 2, "goals": 1, "assists": 0.5, "team": "TOR"},
    "Mitch Marner": {"pts": 2, "goals": 0.5, "assists": 1, "team": "TOR"},
    "David Pastrnak": {"pts": 2, "goals": 1, "assists": 0.5, "team": "BOS"},
    "Artemi Panarin": {"pts": 2, "goals": 0.5, "assists": 1, "team": "NYR"},
    "Bo Horvat": {"pts": 1, "goals": 1, "assists": 0.5, "team": "NYI"},
    "Matthew Tkachuk": {"pts": 2, "goals": 0.5, "assists": 1, "team": "FLA"},
    "Nikita Kucherov": {"pts": 2, "goals": 0.5, "assists": 1, "team": "TBL"},
    "Sebastian Aho": {"pts": 2, "goals": 0.5, "assists": 1, "team": "CAR"},
    "Jack Hughes": {"pts": 2, "goals": 0.5, "assists": 1, "team": "NJD"},
    "Sidney Crosby": {"pts": 2, "goals": 0.5, "assists": 1, "team": "PIT"},
    "Alex Ovechkin": {"pts": 2, "goals": 1, "assists": 0.5, "team": "WSH"},
    "Travis Konecny": {"pts": 1, "goals": 1, "assists": 0.5, "team": "PHI"},
    "Tage Thompson": {"pts": 1, "goals": 1, "assists": 0.5, "team": "BUF"},
    "Brady Tkachuk": {"pts": 1, "goals": 0.5, "assists": 0.5, "team": "OTT"},
    "Cole Caufield": {"pts": 1, "goals": 1, "assists": 0.5, "team": "MTL"},
    "Lucas Raymond": {"pts": 1, "goals": 0.5, "assists": 0.5, "team": "DET"},
    "Johnny Gaudreau": {"pts": 1, "goals": 0.5, "assists": 0.5, "team": "CBJ"},
    "Robert Thomas": {"pts": 1, "goals": 0.5, "assists": 0.5, "team": "STL"},
    "Kirill Kaprizov": {"pts": 2, "goals": 0.5, "assists": 1, "team": "MIN"},
    "Roman Josi": {"pts": 1, "goals": 0.5, "assists": 0.5, "team": "NSH"},
    "Jason Robertson": {"pts": 1, "goals": 0.5, "assists": 0.5, "team": "DAL"},
    "Mark Scheifele": {"pts": 1, "goals": 0.5, "assists": 0.5, "team": "WPG"},
    "Nazem Kadri": {"pts": 1, "goals": 0.5, "assists": 0.5, "team": "CGY"},
    "Leo Carlsson": {"pts": 1, "goals": 1, "assists": 0.5, "team": "ANA"},
    "Anze Kopitar": {"pts": 1, "goals": 0.5, "assists": 0.5, "team": "LA"},
    "Timo Meier": {"pts": 1, "goals": 1, "assists": 0.5, "team": "SJ"},
    "Jack Eichel": {"pts": 2, "goals": 0.5, "assists": 1, "team": "VGK"},
    "Clayton Keller": {"pts": 1, "goals": 0.5, "assists": 0.5, "team": "ARI"},
    "Patrick Kane": {"pts": 1, "goals": 0.5, "assists": 0.5, "team": "CHI"},
    # MLB Players
    "Aaron Judge": {"hits": 1.5, "runs": 1, "RBI": 1, "home_runs": 0.5, "team": "NYY"},
    "Juan Soto": {"hits": 1.5, "runs": 1, "RBI": 0.5, "home_runs": 0.5, "team": "NYY"},
    "Mookie Betts": {"hits": 1.5, "runs": 1, "RBI": 0.5, "home_runs": 0.5, "team": "LAD"},
    "Shohei Ohtani": {"strikeouts": 7, "hits": 1, "runs": 1, "RBI": 0.5, "home_runs": 0.5, "team": "LAD"},
    "Rafael Devers": {"hits": 1.5, "RBI": 1, "home_runs": 0.5, "team": "BOS"},
    "Kyle Schwarber": {"home_runs": 0.5, "runs": 1, "RBI": 0.5, "team": "PHI"},
    "Jose Altuve": {"hits": 1.5, "runs": 1, "RBI": 0.5, "team": "HOU"},
    "Ronald Acuna Jr.": {"runs": 1.5, "hits": 1, "RBI": 0.5, "home_runs": 0.5, "team": "ATL"},
    "Manny Machado": {"hits": 1.5, "RBI": 1, "home_runs": 0.5, "team": "SD"},
    "Nolan Arenado": {"hits": 1.5, "RBI": 1, "home_runs": 0.5, "team": "STL"},
    "Christopher Morel": {"home_runs": 0.5, "runs": 0.5, "RBI": 0.5, "team": "CHC"},
    "Francisco Lindor": {"hits": 1.5, "runs": 1, "RBI": 0.5, "home_runs": 0.5, "team": "NYM"},
    "Vladimir Guerrero Jr.": {"hits": 1.5, "RBI": 1, "home_runs": 0.5, "team": "TOR"},
    "Julio Rodriguez": {"runs": 1, "hits": 1.5, "RBI": 0.5, "home_runs": 0.5, "team": "SEA"},
    "Corey Seager": {"hits": 1.5, "RBI": 1, "home_runs": 0.5, "team": "TEX"},
    "Christian Yelich": {"home_runs": 0.5, "runs": 1, "RBI": 0.5, "team": "MIL"},
    "Jose Ramirez": {"hits": 1.5, "RBI": 1, "home_runs": 0.5, "team": "CLE"},
    "Logan Webb": {"strikeouts": 6, "hits": 1.5, "runs": 0.5, "team": "SF"},
    "Elly De La Cruz": {"runs": 1, "hits": 1.5, "RBI": 0.5, "home_runs": 0.5, "team": "CIN"},
    "Jazz Chisholm": {"home_runs": 0.5, "runs": 0.5, "RBI": 0.5, "team": "MIA"},
    "Carlos Correa": {"hits": 1.5, "RBI": 1, "home_runs": 0.5, "team": "MIN"},
    "Mike Trout": {"home_runs": 0.5, "runs": 1, "RBI": 0.5, "team": "LAA"},
    "Ryan McMahon": {"hits": 1.5, "RBI": 1, "home_runs": 0.5, "team": "COL"},
    "Lawrence Butler": {"runs": 0.5, "hits": 1, "RBI": 0.5, "team": "OAK"},
    "Bobby Witt Jr.": {"hits": 1.5, "runs": 1, "RBI": 0.5, "home_runs": 0.5, "team": "KC"},
    "Isaac Paredes": {"hits": 1.5, "RBI": 1, "home_runs": 0.5, "team": "TB"},
    "Oneil Cruz": {"home_runs": 0.5, "runs": 0.5, "RBI": 0.5, "team": "PIT"},
    "Gunnar Henderson": {"runs": 1, "hits": 1.5, "RBI": 0.5, "home_runs": 0.5, "team": "BAL"},
    "Ketel Marte": {"hits": 1.5, "RBI": 0.5, "home_runs": 0.5, "team": "AZ"},
    "James Wood": {"runs": 0.5, "hits": 1, "RBI": 0.5, "team": "WSH"},
}

# Rest day adjustment settings
REST_DAY_ADJUSTMENT = {
    # How much to reduce team projected points (50% of player's avg pts)
    "team_proj_reduction_pct": 0.50,
    # How many points to shift spread toward the team missing their star (5-8 pts)
    "spread_shift": 6,
    # How much to lower O/U total when star is out (8-12 pts)
    "total_reduction": 10,
}
