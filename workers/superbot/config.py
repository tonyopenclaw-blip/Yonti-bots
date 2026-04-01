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
SERIES_TICKER = "KXBTC15M"
MARKETS_LIMIT = 20

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
MIN_KELLY_BET = 0.10   # Minimum bet when using Kelly sizing
MAX_KELLY_BET = MAX_BET  # Cap Kelly bets at max_bet

# =============================================================================
# STRATEGY THRESHOLDS
# =============================================================================

# DEEP BUY Strategy: YES < $0.15 → buy, ride to expiry, NO stop loss
DEEP_BUY_MAX_PRICE = 0.15
DEEP_MIN_TIME_LEFT_SEC = 60   # At least 1 minute before expiry

# DRIFT BUY Strategy: YES $0.35-$0.45 → mean reversion, TP +25%, SL -15%
DRIFT_BUY_MIN_PRICE = 0.35
DRIFT_BUY_MAX_PRICE = 0.45
DRIFT_MIN_TIME_LEFT_SEC = 120  # At least 2 minutes before expiry

# DRIFT SHORT Strategy: YES $0.55-$0.65 → sell overpriced, TP +25%, SL -15%
DRIFT_SHORT_MIN_PRICE = 0.55
DRIFT_SHORT_MAX_PRICE = 0.65

# Take Profit and Stop Loss percentages for DRIFT strategies
DRIFT_TP_PCT = 0.25    # Take profit at 25% gain
DRIFT_SL_PCT = 0.15    # Stop loss at 15% loss

# =============================================================================
# TRADING LOOP CONFIG
# =============================================================================
LOOP_INTERVAL_SEC = 10   # Check markets every 10 seconds
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
