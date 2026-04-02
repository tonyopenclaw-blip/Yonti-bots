# config.py - Superbot Configuration
# All safety thresholds and settings for Kalshi trading

import os
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).parent
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "superbot.log"
REPORT_FILE = BASE_DIR / "report.html"

# Ensure directories exist
LOG_DIR.mkdir(exist_ok=True)

# =============================================================================
# KALSHI API CONFIG
# =============================================================================
KALSHI_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
MARKETS_LIMIT = 20

# Coins to trade (8-coin multi-market strategy)
COINS = ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE', 'HYPE', 'BNB', 'ADA']
SERIES_TICKERS = {coin: f'KX{coin}15M' for coin in COINS}

# Auth - set via environment variable KALSHI_ACCESS_KEY
KALSHI_ACCESS_KEY = os.getenv("KALSHI_ACCESS_KEY", "")

# =============================================================================
# PAPER TRADING CONFIG
# =============================================================================
PAPER_MODE = True  # Always paper trading first
PAPER_BALANCE = 100.00  # Starting paper balance
BALANCE_FLOOR = 3.00    # Auto-reset if cash falls below this
BALANCE_RESET_AMOUNT = 100.00  # Amount to reset to when hitting floor

# =============================================================================
# TRADING LIMITS (Kelvin Dollar Safety Rules)
# =============================================================================
MAX_BET = 2.00  # Maximum bet size per trade (safety limit)
MIN_BET = 0.10  # Minimum bet size

# Kelly Criterion Sizing (based on CASH AVAILABLE, not original seed)
KELLY_FRACTION = 0.25  # Use 25% of Kelly (conservative)
MIN_KELLY_BET = 2.00   # Minimum bet when using Kelly sizing ($2 hard floor)
MAX_KELLY_BET = 2.00   # Maximum bet when using Kelly sizing ($2 hard cap)
KELLY_TRACKED_TRADES = 50  # Number of recent trades to track per strategy
KELLY_MAX_CAP = 0.15   # Never bet more than 15% of balance (half-Kelly safety)

# =============================================================================
# STRATEGY THRESHOLDS
# =============================================================================

# DEEP SHORT Strategy: YES < $0.15 → SELL tails (short YES), fade the longshot
# Research shows low-probability outcomes are overbet (longshot bias)
# Fading the longshot = betting AGAINST low-prob events is more profitable
DEEP_SHORT_MAX_PRICE = 0.15
DEEP_MIN_TIME_LEFT_SEC = 60   # At least 1 minute before expiry

# DRIFT BUY Strategy: YES $0.35-$0.65 → mean reversion, TP +25%, SL -15%
DRIFT_BUY_MIN_PRICE = 0.35
DRIFT_BUY_MAX_PRICE = 0.65
DRIFT_MIN_TIME_LEFT_SEC = 120  # At least 2 minutes before expiry

# DRIFT SHORT Strategy: YES $0.55-$0.75 → sell overpriced, TP +25%, SL -15%
DRIFT_SHORT_MIN_PRICE = 0.55
DRIFT_SHORT_MAX_PRICE = 0.75

# Take Profit and Stop Loss percentages for DRIFT strategies
DRIFT_TP_PCT = 0.25    # Take profit at 25% gain (used for DRIFT_SHORT)
DRIFT_TP_PRICE = 0.95  # TP at $0.95+ for DRIFT_BUY (lock in near-wins)
DRIFT_SL_PCT = 0.25    # Stop loss at 25% loss (increased from 15% to give trades more room)

# =============================================================================
# AI PROBABILITY ESTIMATION
# =============================================================================
AI_PROBABILITY_ENABLED = False  # Enable AI probability estimation via Claude
AI_EDGE_THRESHOLD = 0.05         # Minimum edge required to trade (5%)

# =============================================================================
# TRADING COOLDOWN & DAILY STOP-LOSS (Added from Nerd's research)
# =============================================================================
COOLDOWN_CYCLES = 0              # NO COOLDOWNS - Tony said trade freely
DAILY_STOP_LOSS_PCT = 0.20      # Portfolio daily stop-loss at 20% (stop and reset)

# =============================================================================
# TRADING LOOP CONFIG - Smart Polling (Recorder's Approach)
# =============================================================================
IDLE_POLL_INTERVAL_SEC = 10    # When NO active markets: poll 1 series per 10 sec
ACTIVE_POLL_INTERVAL_SEC = 1   # When market IS active: poll every 1 sec
LOOP_INTERVAL_SEC = 10   # Legacy fallback
MAX_OPEN_POSITIONS = 5    # Maximum concurrent positions

# =============================================================================
# LOGGING CONFIG
# =============================================================================
LOG_LEVEL = "INFO"  # DEBUG, INFO, WARNING, ERROR
LOG_FORMAT = "%(asctime)s | %(levelname)s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# =============================================================================
# REPORTING CONFIG
# =============================================================================
REPORT_TITLE = "Superbot Paper Trading Report"
