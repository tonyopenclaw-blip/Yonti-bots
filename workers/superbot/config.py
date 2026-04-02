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
MAX_BET = 5.00  # Maximum bet size per trade (safety limit)
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

# DEEP SHORT Strategy: KILLED - disabled via DEEP_SHORT_ENABLED=False
# Research shows low-probability outcomes are overbet (longshot bias)
# Fading the longshot = betting AGAINST low-prob events is more profitable
DEEP_SHORT_ENABLED = False  # DISABLED - no trades will ever trigger
DEEP_SHORT_MAX_PRICE = 0.01  # Effectively disabled - no YES price will be < $0.01
DEEP_MIN_TIME_LEFT_SEC = 60   # At least 1 minute before expiry

# DRIFT BUY - entry zone (tightened to avoid dead zone)
DRIFT_BUY_MIN_PRICE = 0.30
DRIFT_BUY_MAX_PRICE = 0.45  # was 0.50 — enter on dips to $0.45 max
DRIFT_MIN_TIME_LEFT_SEC = 120  # At least 2 minutes before expiry

# DRIFT SHORT - entry zone (tightened: only enter below $0.70)
DRIFT_SHORT_ENABLED = True
DRIFT_SHORT_MIN_PRICE = 0.50  # was 0.55
DRIFT_SHORT_MAX_PRICE = 0.70  # was 0.65 — skip if above $0.70
DRIFT_SHORT_SL_PRICE = 0.75   # Stop loss at $0.75 — exit immediately if price reaches this

# Dead zone - NO TRADE in this range (widened)
DEAD_ZONE_MIN = 0.50  # was 0.45
DEAD_ZONE_MAX = 0.60  # was 0.55

# Take Profit and Stop Loss percentages for DRIFT strategies
DRIFT_TP_PCT = 0.25    # Take profit at 25% gain (used for DRIFT_SHORT)
DRIFT_TP_PRICE = 0.95  # TP at $0.95+ for DRIFT_BUY (lock in near-wins)

# Stop loss - ABSOLUTE prices (Nerd's research, not percentage)
DRIFT_BUY_STOP_LOSS = 0.25   # was 25% relative - absolute $0.25
DRIFT_SHORT_STOP_LOSS = 0.75  # was 25% relative - absolute $0.75

# Keep old SL_PCT for backwards compat but prefer absolute
DRIFT_SL_PCT = 0.25    # Deprecated: use DRIFT_BUY_STOP_LOSS / DRIFT_SHORT_STOP_LOSS

# =============================================================================
# AI PROBABILITY ESTIMATION
# =============================================================================
AI_PROBABILITY_ENABLED = False  # Enable AI probability estimation via Claude
AI_EDGE_THRESHOLD = 0.05         # Minimum edge required to trade (5%)

# =============================================================================
# TRADING COOLDOWN & DAILY STOP-LOSS (Added from Nerd's research)
# =============================================================================
COOLDOWN_CYCLES = 0              # No cooldown - maximum trading frequency
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
