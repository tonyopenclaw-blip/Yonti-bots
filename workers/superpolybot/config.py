# config.py - SuperPolybot Configuration
# Paper trading for Polymarket 5-minute binary contracts

import os
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).parent
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "superpolybot.log"
REPORT_FILE = BASE_DIR / "report.json"

LOG_DIR.mkdir(exist_ok=True)

# =============================================================================
# POLYMARKET API CONFIG
# =============================================================================
# GraphQL endpoint for market data
POLYMARKET_GRAPH_URL = "https://gateway.thegraph.com/api/subgraphs/name/polymarket/markets"
# CLOB endpoint for order placement
POLYMARKET_CLOB_URL = "https://clob.polymarket.com"

# API Key for The Graph (free tier available)
GRAPH_API_KEY = os.getenv("GRAPH_API_KEY", "")

# Market filtering - look for 5-min binary contracts
# Polymarket markets have tags like "cryptocurrency", "binary"
MARKET_STATUS = "active"  # Looking for open/active markets
MARKETS_LIMIT = 50

# =============================================================================
# TRADING PAIRS - Crypto binaries on Polymarket
# =============================================================================
# Polymarket has various crypto binary markets
# We'll track these and look for 5-minute contracts
TRADING_PAIRS = [
    "BTC",
    "ETH",
    "SOL",
]

# =============================================================================
# PAPER TRADING CONFIG
# =============================================================================
PAPER_MODE = True
PAPER_BALANCE = 100.00
BALANCE_FLOOR = 10.00
BALANCE_RESET_AMOUNT = 100.00

# =============================================================================
# TRADING LIMITS
# =============================================================================
MAX_BET = 2.00    # Max $2 per trade
MIN_BET = 0.05    # Minimum bet
MAX_POSITIONS = 3  # Max concurrent positions
KELLY_MAX_CAP = 0.20   # Max 20% of bankroll per trade
FIXED_KELLY_PCT = 0.04  # 4% fallback

# =============================================================================
# POLLING INTERVALS
# =============================================================================
IDLE_POLL_INTERVAL_SEC = 30   # When no active markets
ACTIVE_POLL_INTERVAL_SEC = 5   # When markets are active
MARKET_DURATION_SEC = 300      # 5 minutes (300 seconds)

# =============================================================================
# STRATEGY THRESHOLDS - Momentum Matrix
# =============================================================================
# Price entry range: only trade when market price is $0.20-$0.80
MIN_ENTRY_PRICE = 0.20
MAX_ENTRY_PRICE = 0.80

# RSI thresholds
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
RSI_PERIOD = 4

# Trailing stop (from Superbot)
TRAILING_TRIGGER_PCT = 0.30  # Activate after 30% profit
TRAILING_BUFFER_PCT = 0.40    # 40% buffer from peak

# Entry/Exit matrix timing
GRACE_PERIOD_SEC = 30         # Wait 30s before entering
MIN_TIME_LEFT_SEC = 30        # Don't enter if <30s left

# =============================================================================
# COINBASE API CONFIG (for price data - same as Superbot)
# =============================================================================
COINBASE_API = "https://api.exchange.coinbase.com"
COINBASE_PRODUCTS = {
    "BTC": "BTC-USD",
    "ETH": "ETH-USD",
    "SOL": "SOL-USD",
}

# =============================================================================
# LOGGING
# =============================================================================
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s | %(levelname)s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
