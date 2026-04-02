# config.py - Flip Bot Configuration
# Game Winner flip trading bot for Kalshi prediction markets

import os
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).parent
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "flip.log"
DATA_DIR = BASE_DIR / "data"

# Ensure directories exist
LOG_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

# =============================================================================
# KALSHI API CONFIG
# =============================================================================
KALSHI_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
MARKETS_LIMIT = 100

# Game Winner series - each game has 2 markets (one per team)
# Format: KXNBAGAME-26APR01INDCHI-IND and KXNBAGAME-26APR01INDCHI-CHI
SPORTS_SERIES = {
    'NBA_GAME': 'KXNBAGAME',      # NBA game winners
    # Add more as needed:
    # 'NHL_GAME': 'KXNHIGAME',
    # 'MLB_GAME': 'KXMLBGAME',
}

# Auth - set via environment variable KALSHI_ACCESS_KEY
KALSHI_ACCESS_KEY = os.getenv("KALSHI_ACCESS_KEY", "0ebe781e-ce07-4e19-98eb-0d2d8e0ea20b")

# =============================================================================
# PAPER TRADING CONFIG
# =============================================================================
PAPER_MODE = True
PAPER_BALANCE = 100.00

# =============================================================================
# FLIP STRATEGY CONFIG - Game Winner Edition
# =============================================================================
# Entry range: both sides near 50/50 (e.g., 46¢ vs 54¢)
ENTRY_PRICE_MIN = 0.40   # Minimum price on either side to enter
ENTRY_PRICE_MAX = 0.60   # Maximum price on either side to enter

# Price threshold for taking profit / flipping
TAKE_PROFIT_THRESHOLD = 0.85  # Sell when price >= $0.85
MIN_PROFIT_THRESHOLD = 0.70   # Minimum price to consider selling

# Time filters
MIN_TIME_LEFT_SEC = 300      # At least 5 minutes before market expires
MAX_TIME_LEFT_SEC = 6 * 3600 # Markets expiring within 6 hours

# Position sizing - $2 max per side, $4 max per game pair
FLIP_POSITION_SIZE = 2.00   # $2 per side of the flip
MIN_POSITION_SIZE = 0.50
MAX_POSITION_SIZE = 2.00

# Poll interval - 3 seconds for sports odds
POLL_INTERVAL_SEC = 3

# =============================================================================
# NEW MARKET DETECTOR CONFIG
# =============================================================================
NEW_MARKET_LOOKBACK_MINUTES = 5    # Detect markets opened within last 5 minutes
NEW_MARKET_BUY_MIN = 0.40          # Lower bound for new market buy zone
NEW_MARKET_BUY_MAX = 0.60          # Upper bound for new market buy zone

# =============================================================================
# LOGGING CONFIG
# =============================================================================
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s | %(levelname)s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# =============================================================================
# REPORTING CONFIG
# =============================================================================
STATS_REPORT_INTERVAL_SEC = 300  # Report stats every 5 minutes
