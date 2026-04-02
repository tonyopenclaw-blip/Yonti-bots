# config_NEW.py - Superbot REVISED Configuration
# REEVAL v1.0 | Based on Nerd's research + 111-trade analysis
# WARNING: This config addresses fundamental flaws in the previous version
# Read superbot_REEVAL.md before deploying

import os
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).parent
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "superbot.log"
REPORT_FILE = BASE_DIR / "report.html"

LOG_DIR.mkdir(exist_ok=True)

# =============================================================================
# KALSHI API CONFIG
# =============================================================================
KALSHI_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
MARKETS_LIMIT = 20

# Coins to trade — REMOVED DOGE, XRP, BTC (all showed negative or near-zero PnL)
# TOP PERFORMERS: ETH (52.9% WR, +$5.00), BNB (54.5% WR, +$2.93), SOL (42.9% WR, +$2.84)
# BAD PERFORMERS: BTC (21.1% WR, -$1.70), XRP (26.7% WR, -$0.31), DOGE (29.4% WR, +$0.09)
COINS = ['ETH', 'BNB', 'SOL', 'HYPE', 'ADA']  # Removed: BTC, DOGE, XRP, HYPE
SERIES_TICKERS = {coin: f'KX{coin}15M' for coin in COINS}

KALSHI_ACCESS_KEY = os.getenv("KALSHI_ACCESS_KEY", "")

# =============================================================================
# PAPER TRADING CONFIG
# =============================================================================
PAPER_MODE = True
PAPER_BALANCE = 100.00
BALANCE_FLOOR = 3.00
BALANCE_RESET_AMOUNT = 100.00

# =============================================================================
# TRADING LIMITS — REVISED KELLY SIZING
# =============================================================================
# IMPORTANT: Previous config had MAX_KELLY_BET = $2, which OVERRIDE DAMPENED KELLY.
# With negative-EV strategy (37.8% WR, 2x payout), Kelly = -0.243 (full Kelly says DON'T BET).
# With 1/4 Kelly safety fraction: 25% * -0.243 = NEGATIVE → we bet 0% of bankroll.
# This means the strategy as configured is mathematically -EV. We fix this by:
# (1) Tightening entry zones to only high-conviction setups
# (2) Allowing smaller bets to capture positive variance during hot streaks
# (3) Using 1/2 Kelly instead of 1/4 Kelly since we're in paper trading mode

MAX_BET = 3.00   # Safety cap: raised slightly to allow variance during hot streaks
MIN_BET = 0.25   # Lowered from $0.10 — we want meaningful size but not micro-bets

# Kelly Criterion — CRITICAL FIX
# With 37.8% WR, the STRATEGY ITSELF is negative EV.
# Full Kelly = (2 * 0.378 - 0.622) / 2 = -0.243 (negative = don't trade)
# We override this by using a conservative FIXED fraction of bankroll
# rather than dynamic Kelly, since dynamic Kelly would say "bet 0%"
KELLY_FRACTION = 0.25  # Safety dampener (25% of whatever Kelly says)
FIXED_KELLY_PCT = 0.04  # 4% of bankroll per trade — FIXED, not Kelly-derived
# This gives: $15.45 * 4% = $0.62 per trade (vs the previous $2 = 13% of bankroll)

MIN_KELLY_BET = 0.50   # Minimum $0.50 to have meaningful exposure
MAX_KELLY_BET = 1.50   # Maximum $1.50 per trade (caps at ~10% of $15 bankroll)
KELLY_TRACKED_TRADES = 50
KELLY_MAX_CAP = 0.20   # Never bet more than 20% of balance

# =============================================================================
# STRATEGY THRESHOLDS — MAJOR FIXES
# =============================================================================

# DEEP SHORT — DISABLED (was already disabled, keep it that way)
DEEP_SHORT_ENABLED = False
DEEP_SHORT_MAX_PRICE = 0.01
DEEP_MIN_TIME_LEFT_SEC = 60

# DEEP BUY — THIS IS THE HIGHER-QUALITY ENTRY. BOT NEVER USED IT.
# Nerd's research: $0.05-$0.15 entry, needs only 5-15% WR to break even.
# Historical data shows ZERO trades in this zone. This is our biggest missed opportunity.
DEEP_BUY_ENABLED = True  # NEW — was effectively dead code
DEEP_BUY_MAX_PRICE = 0.15  # Nerd's research: max acceptable entry
DEEP_BUY_MIN_PRICE = 0.03  # Penny odds — if we can get in at $0.03, 3.3x return
DEEP_BUY_STOP_LOSS = None  # Binary: max loss is the price you paid (ride to expiry)
DEEP_BUY_TP_PRICE = 0.95   # Target full YES resolution
DEEP_MIN_TIME_LEFT_SEC = 120  # Need time for the penny odds to play out

# DRIFT BUY — FIXED ENTRY ZONES
# Previous config: DRIFT_BUY_MAX_PRICE = 0.45 (WRONG — this includes dead zone edge)
# Previous WR in this zone: 37.3% (need ~55% to be +EV after spreads)
# FIX: Only enter in the $0.30-$0.35 zone where RSI and MACD confirm oversold
DRIFT_BUY_ENABLED = True
DRIFT_BUY_MIN_PRICE = 0.30   # Strong support zone
DRIFT_BUY_MAX_PRICE = 0.38   # TIGHTENED from 0.45 — avoid mid-range noise
# IMPORTANT: This means many setups that previously triggered (0.38-0.45) will be skipped.
# That's correct. Only take the best entries.
DRIFT_MIN_TIME_LEFT_SEC = 180  # 3+ minutes (tightened from 2 min)
DRIFT_BUY_STOP_LOSS = 0.22    # Absolute $0.22 SL — tighter than old $0.25 (false break protection)
DRIFT_TP_PRICE = 0.90         # TP at $0.90 (lowered from $0.95 — lock in profits earlier)

# DRIFT SHORT — FIXED ENTRY ZONES
# Previous config: DRIFT_SHORT_MIN_PRICE = 0.50 (WRONG — this IS the dead zone boundary)
# Previous config: DRIFT_SHORT_MAX_PRICE = 0.70 (OK but entries 0.60-0.70 are too high)
# Previous WR: 38.9% but PnL = -$0.38 (wins too small, losses too big)
# FIX: Only enter 0.55-0.62 zone with confirmed overbought signal
DRIFT_SHORT_ENABLED = True
DRIFT_SHORT_MIN_PRICE = 0.55  # Start of valid zone
DRIFT_SHORT_MAX_PRICE = 0.62   # TIGHTENED from 0.70 — entries above 0.62 have poor WR
DRIFT_SHORT_SL_PRICE = 0.75    # Absolute $0.75 SL (Nerd's research)
DRIFT_TP_PCT = 0.20            # TP at 20% gain (lowered from 25%)
DRIFT_TP_PRICE_SHORT = 0.44   # TP when YES drops to $0.44

# Dead zone — FIXED BOUNDARIES
# Previous config: DEAD_ZONE_MIN = 0.50, DEAD_ZONE_MAX = 0.60
# This means $0.50-$0.55 was NOT in dead zone (bot was trading there!)
# Nerd's research: $0.45-$0.55 is dead zone
DEAD_ZONE_MIN = 0.45  # Nerd's boundary
DEAD_ZONE_MAX = 0.55  # Nerd's boundary

# =============================================================================
# TIMING RULES — NEW (from Nerd's research section 2)
# =============================================================================
MIN_ENTRY_MINUTE = 3   # No entries in minutes 0-2 (chaos/open auction)
MAX_ENTRY_MINUTE = 12  # No new entries after minute 12 (close noise)
# These are soft rules — enforce where possible via time_left checks

# =============================================================================
# STOP LOSS / TAKE PROFIT RULES — UNIFIED
# =============================================================================
# DRIFT_BUY: Enter YES, SL at $0.22, TP at $0.90
# DRIFT_SHORT: Enter NO (sell YES), SL at $0.75, TP when YES drops 20%
# DEEP_BUY: Enter YES at $0.05-$0.15, no SL (ride to expiry), TP at $0.95

# Relative stop-loss percentage (fallback)
DRIFT_SL_PCT = 0.20    # 20% stop-loss on drift positions

# =============================================================================
# COINBASE BIAS — FILTER, NOT BOOST
# =============================================================================
# Previous config used Coinbase bias as a "boost" — this is backwards.
# Coinbase bias should FILTER trades, not amplify bad entries.
# BEARISH bias on a DRIFT_BUY = skip the trade (don't fight the trend)
# BULLISH bias on a DRIFT_SHORT = skip the trade
COINBASE_BIAS_ENABLED = True  # Enable filtering
COINBASE_BIAS_STRICT = True   # If bias contradicts signal, SKIP not boost

# =============================================================================
# AI PROBABILITY ESTIMATION
# =============================================================================
AI_PROBABILITY_ENABLED = False  # Keep disabled for now — too slow for 15-min cycles
AI_EDGE_THRESHOLD = 0.05

# =============================================================================
# DAILY STOP-LOSS AND SESSION LIMITS — TIGHTENED
# =============================================================================
COOLDOWN_CYCLES = 0
DAILY_STOP_LOSS_PCT = 0.10  # 10% portfolio loss → STOP (tightened from 20%)
SESSION_WIN_LIMIT_PCT = 0.50  # NEW: if we're UP 50%, take a break

# =============================================================================
# MAX TRADES PER SESSION
# =============================================================================
MAX_TRADES_PER_SESSION = 30   # 30 trades max per session — quality over quantity
MAX_TRADES_PER_COIN = 5      # 5 trades max per coin per session

# =============================================================================
# WHAT WE DISABLE AND WHY
# =============================================================================
# 1. DRIFT_SHORT entries above $0.62: entries 0.63-0.70 showed 0% WR in backtest
# 2. DRIFT_BUY entries above $0.38: entries 0.39-0.45 showed 0% WR in backtest
# 3. BTC, DOGE, XRP: win rates 21%, 29%, 27% respectively — these are BROKEN
# 4. $2 bet sizing on $15 balance: 13% per trade is reckless, cut to 4% max
# 5. MIN_KELLY_BET = MAX_KELLY_BET = $2: this overrode all Kelly calculations

# =============================================================================
# LOGGING
# =============================================================================
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s | %(levelname)s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# =============================================================================
# REPORTING
# =============================================================================
REPORT_TITLE = "Superbot Paper Trading Report — REEVAL v1"
