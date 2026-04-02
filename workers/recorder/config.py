# config.py - Recorder Configuration
# Records 15-min crypto market data for analysis

import os
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_FILE = DATA_DIR / "market_data.jsonl"
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "recorder.log"

# Ensure directories exist
DATA_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

# =============================================================================
# KALSHI API CONFIG
# =============================================================================
KALSHI_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
MARKETS_LIMIT = 20

# Coins to record (8-coin strategy)
COINS = ['BTC', 'ETH', 'SOL', 'ADA', 'DOGE', 'XRP', 'HYPE', 'BNB']
SERIES_TICKERS = {coin: f'KX{coin}15M' for coin in COINS}

# Auth - set via environment variable KALSHI_ACCESS_KEY
KALSHI_ACCESS_KEY = os.getenv("KALSHI_ACCESS_KEY", "")

# =============================================================================
# RECORDER CONFIG
# =============================================================================
# Polling intervals - adaptive based on activity
ACTIVE_POLL_INTERVAL_SEC = 1   # Poll every 1 second when markets ARE active
IDLE_POLL_INTERVAL_SEC = 10    # Poll every 10 seconds when NO markets are active

# For backwards compatibility
POLL_INTERVAL_SEC = ACTIVE_POLL_INTERVAL_SEC

# =============================================================================
# LOGGING CONFIG
# =============================================================================
LOG_LEVEL = "INFO"  # DEBUG, INFO, WARNING, ERROR
LOG_FORMAT = "%(asctime)s | %(levelname)s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
