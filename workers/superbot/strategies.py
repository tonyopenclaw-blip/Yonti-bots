import time
# strategies.py - Superbot Trading Strategies
# CONFIDENCE SCHEMA v1.0 - Size trades based on signal strength, let winners run

import logging
import os
import subprocess
import json
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, List
from collections import deque
from enum import Enum

from config import (
    MAX_BET, MIN_BET,
    DEEP_SHORT_ENABLED, DEEP_SHORT_MAX_PRICE, DEEP_MIN_TIME_LEFT_SEC,
    DEEP_BUY_ENABLED, DEEP_BUY_MAX_PRICE, DEEP_BUY_MIN_PRICE, DEEP_BUY_TP_PRICE,
    DRIFT_BUY_MIN_PRICE, DRIFT_BUY_MAX_PRICE, DRIFT_MIN_TIME_LEFT_SEC,
    DRIFT_SHORT_MIN_PRICE, DRIFT_SHORT_MAX_PRICE, DRIFT_SHORT_SL_PRICE,
    DRIFT_TP_PCT, DRIFT_SL_PCT, KELLY_TRACKED_TRADES, KELLY_MAX_CAP,
    DRIFT_TP_PRICE,  # New: absolute TP price threshold
    DEAD_ZONE_MIN, DEAD_ZONE_MAX,  # Dead zone - no trade
    DRIFT_BUY_STOP_LOSS, DRIFT_SHORT_STOP_LOSS,  # Absolute stop loss prices
    AI_EDGE_THRESHOLD,  # Minimum edge required (5%)
    AI_PROBABILITY_ENABLED,  # Enable AI probability estimation
    COINBASE_API, COINBASE_PRODUCTS,  # For First Cross coin price tracking
    FIXED_KELLY_PCT,
)

# === TONY'S ENTRY PRICE FILTER: Only enter when share price is $0.20-$0.80 ===
MIN_ENTRY_PRICE = 0.20
MAX_ENTRY_PRICE = 0.80

# === TONY'S TWO-STAGE STOP SYSTEM ===
# Stage 1: TIME-SCALED STOP - 80% at open → 20% at close (15 min)
# Stage 2: TRAILING STOP (only after +30% profit) - trail from there
INITIAL_STOP_PCT = 0.80       # 80% stop at open (0 min)
FINAL_STOP_PCT = 0.20         # 20% stop at close (15 min)
MARKET_DURATION_SEC = 900      # 15 minutes
TRAILING_TRIGGER_PCT = 0.30   # 30% profit before trailing stop activates
TRAILING_BUFFER_PCT = 0.40    # 40% buffer from peak
MIN_STOP_PCT = 0.30           # Never tighter than 30% in final 3 min
import requests
from kalshi_api import Market

logger = logging.getLogger(__name__)


def get_coinbase_bias(coin: str) -> str:
    """
    Returns 'bullish', 'bearish', or 'neutral' based on Coinbase.
    Reads from Coinbase fetcher's last output.
    """
    bias_file = "/home/ubuntu/.openclaw/workspace/workers/coinbase/last_bias.json"
    if os.path.exists(bias_file):
        try:
            with open(bias_file) as f:
                biases = json.load(f)
                return biases.get(coin, 'neutral')
        except (json.JSONDecodeError, IOError):
            return 'neutral'
    return 'neutral'


class Strategy(Enum):
    # DEPRECATED: DRIFT_BUY and DRIFT_SHORT disabled per Nerd's strategy v2
    DEEP_SHORT = "deep_short"  # Disabled
    DEEP_BUY = "deep_buy"      # NEW: penny odds - buy YES at $0.03-$0.15
    DRIFT_BUY = "drift_buy"    # DISABLED - drift doesn't work
    DRIFT_SHORT = "drift_short"  # DISABLED - drift doesn't work
    MOMENTUM = "momentum"        # PRIMARY: Momentum + extreme = buy
    FIRST_CROSS = "first_cross"  # PRIMARY: Real cross through floor strike
    MOMENTUM_FORCE = "momentum_force"  # FALLBACK: Wait 60s, no cross, force entry
    NONE = "none"


class FirstCrossCoinTracker:
    """
    Tracks when the coin price crosses the Kalshi floor_strike (target price).

    Tony's First Cross Strategy (from target_cross_tracker.py):
    1. At market open: get floor_strike (target price) from Kalshi
    2. Every 5s: track coin price via Coinbase WebSocket
    3. When coin price crosses the target price in either direction → trade in that direction (UP=YES, DOWN=NO)
    4. Use trailing stop as configured (same for both YES and NO)

    The key insight is that when BTC/ETH/SOL price crosses the Kalshi target price,
    the market tends to follow in that direction.
    """

    def __init__(self):
        # Per-ticker coin crossing state
        self._crossings: Dict[str, Dict] = {}
        self._coin_prices: Dict[str, float] = {}  # Current coin prices

    def get_coin_price(self, coin: str) -> Optional[float]:
        """Fetch current coin price from Coinbase API."""
        product_id = COINBASE_PRODUCTS.get(coin.upper())
        if not product_id:
            return None

        try:
            url = f"{COINBASE_API}/products/{product_id}/ticker"
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            data = response.json()
            price = float(data.get('price', 0))
            self._coin_prices[coin] = price
            return price
        except Exception as e:
            logger.debug(f"Coinbase price fetch failed for {coin}: {e}")
            return self._coin_prices.get(coin)

    def get_floor_strike(self, ticker: str, api) -> Optional[float]:
        """Fetch floor_strike (target price) for a market from Kalshi."""
        result = api._get(f"/markets/{ticker}")
        if "error" in result:
            logger.warning(f"Failed to get floor_strike for {ticker}: {result['error']}")
            return None

        market_data = result.get("market", {})
        floor_strike = market_data.get("floor_strike")
        if floor_strike is not None:
            return float(floor_strike)

        # Fallback: parse from yes_sub_title
        import re
        yes_sub_title = market_data.get("yes_sub_title", "")
        if "Target Price:" in yes_sub_title:
            match = re.search(r'\$?([\d,]+\.?\d*)', yes_sub_title)
            if match:
                return float(match.group(1).replace(',', ''))

        return None

    def check_cross(self, ticker: str, coin: str, target_price: float, api) -> Optional[str]:
        """
        Check if coin price has crossed the target price.
        Returns "up" if coin crossed above target, "down" if below, None if no cross yet.
        """
        if ticker not in self._crossings:
            self._crossings[ticker] = {
                'crossed': False,
                'direction': None,
                'cross_price': None,
                'target_price': target_price,
                'prev_coin_price': None,
                'samples_above': [],
                'samples_below': []
            }
            return None

        state = self._crossings[ticker]
        if state['crossed']:
            return None

        # Get current coin price
        coin_price = self.get_coin_price(coin)
        if coin_price is None:
            return None

        prev_coin_price = state['prev_coin_price']
        state['prev_coin_price'] = coin_price

        # Track samples above/below target
        if coin_price > target_price:
            state['samples_above'].append((time.time(), coin_price))
        else:
            state['samples_below'].append((time.time(), coin_price))

        # Detect first cross: check if we have samples on both sides
        if len(state['samples_above']) > 0 and len(state['samples_below']) > 0:
            first_above = min(ts for ts, _ in state['samples_above'])
            first_below = min(ts for ts, _ in state['samples_below'])

            if first_below < first_above:
                direction = "up"
            else:
                direction = "down"

            state['crossed'] = True
            state['direction'] = direction
            state['cross_price'] = coin_price

            logger.info(
                f"FIRST_CROSS: {ticker} | "
                f"Direction: {direction} | "
                f"Target: ${target_price:,.2f} | "
                f"Coin Price: ${coin_price:,.2f}"
            )
            return direction

        return None

    def get_direction(self, ticker: str) -> Optional[str]:
        """Get the first coin cross direction for a ticker."""
        return self._crossings.get(ticker, {}).get('direction')

    def has_crossed(self, ticker: str) -> bool:
        """Check if ticker has crossed the target price."""
        return self._crossings.get(ticker, {}).get('crossed', False)

    def reset(self, ticker: str):
        """Reset crossing state for a ticker (e.g., when market expires)."""
        if ticker in self._crossings:
            del self._crossings[ticker]


class FirstCrossTracker:
    """
    Tracks the first time price crosses the midpoint ($0.50) for each market.

    Tony's insight: When a price crosses a target level for the first time,
    it usually stays on that side. The first direction of a breakout tends
    to hold in the 15-min window.

    - YES at $0.40, midpoint is $0.50
    - If price CROSSES UP through $0.50 first (from below to above) → YES bias
    - If price CROSSES DOWN through $0.50 first (from above to below) → NO bias
    """

    # Midpoint price for crossing detection
    MIDPOINT = 0.50

    def __init__(self):
        # Per-ticker crossing state: ticker -> {crossed: bool, direction: str, first_price: float}
        self._crossings: Dict[str, Dict] = {}

    def update(self, ticker: str, current_price: float) -> Optional[str]:
        """
        Update crossing state for a ticker.
        Returns the first_cross_direction if crossing just happened, else None.
        """
        if ticker not in self._crossings:
            self._crossings[ticker] = {
                'crossed': False,
                'direction': None,
                'first_price': current_price,
                'prev_price': current_price
            }
            return None

        state = self._crossings[ticker]

        # Already crossed - don't update direction
        if state['crossed']:
            state['prev_price'] = current_price
            return None

        prev_price = state['prev_price']
        state['prev_price'] = current_price

        # Check for crossing
        crossed_up = prev_price < self.MIDPOINT <= current_price
        crossed_down = prev_price > self.MIDPOINT >= current_price

        if crossed_up:
            state['crossed'] = True
            state['direction'] = 'up'
            logger.info(f"FIRST_CROSS: {ticker} crossed UP through ${self.MIDPOINT:.2f} (was ${prev_price:.4f}, now ${current_price:.4f})")
            return 'up'

        if crossed_down:
            state['crossed'] = True
            state['direction'] = 'down'
            logger.info(f"FIRST_CROSS: {ticker} crossed DOWN through ${self.MIDPOINT:.2f} (was ${prev_price:.4f}, now ${current_price:.4f})")
            return 'down'

        return None

    def get_direction(self, ticker: str) -> Optional[str]:
        """Get the first cross direction for a ticker, or None if hasn't crossed."""
        if ticker not in self._crossings:
            return None
        return self._crossings[ticker]['direction'] if self._crossings[ticker]['crossed'] else None

    def has_crossed(self, ticker: str) -> bool:
        """Check if ticker has crossed the midpoint."""
        return self._crossings.get(ticker, {}).get('crossed', False)

    def in_dead_zone(self, price: float) -> bool:
        """Check if price is in the dead zone ($0.45-$0.55)."""
        return DEAD_ZONE_MIN <= price <= DEAD_ZONE_MAX

    def should_wait(self, ticker: str, price: float) -> bool:
        """
        Returns True if we should WAIT and not trade.
        Wait conditions:
        - Price is in dead zone AND hasn't crossed yet
        """
        if self.in_dead_zone(price) and not self.has_crossed(ticker):
            return True
        return False

    def get_preferred_side(self, ticker: str) -> Optional[str]:
        """
        Get the preferred trading side based on first cross direction.
        - Crossed UP first → prefer 'yes' (long bias, drift_buy)
        - Crossed DOWN first → prefer 'no' (short bias, drift_short)
        Returns None if hasn't crossed yet.
        """
        direction = self.get_direction(ticker)
        if direction == 'up':
            return 'yes'
        if direction == 'down':
            return 'no'
        return None

    def reset(self, ticker: str):
        """Reset crossing state for a ticker (e.g., when market expires)."""
        if ticker in self._crossings:
            del self._crossings[ticker]


class StrategyTracker:
    """
    Tracks win rate and win/loss ratio per strategy over recent trades.
    Used for Kelly Criterion sizing based on historical strategy performance.
    """

    def __init__(self, tracked_trades: int = KELLY_TRACKED_TRADES):
        self.tracked_trades = tracked_trades
        # Store recent trade results per strategy: each entry is (pnl, won)
        self._history: Dict[Strategy, deque] = {
            Strategy.DEEP_SHORT: deque(maxlen=tracked_trades),
            Strategy.DEEP_BUY: deque(maxlen=tracked_trades),
            Strategy.DRIFT_BUY: deque(maxlen=tracked_trades),  # DISABLED but track for history
            Strategy.DRIFT_SHORT: deque(maxlen=tracked_trades),  # DISABLED but track for history
            Strategy.MOMENTUM: deque(maxlen=tracked_trades),
            Strategy.FIRST_CROSS: deque(maxlen=tracked_trades),
            Strategy.MOMENTUM_FORCE: deque(maxlen=tracked_trades),
        }

    def record_trade(self, strategy: Strategy, pnl: float):
        """Record a completed trade result for a strategy."""
        won = pnl > 0
        self._history[strategy].append((pnl, won))

    def get_stats(self, strategy: Strategy) -> Tuple[float, float]:
        """
        Get win rate (W) and average win/loss ratio (R) for a strategy.
        Returns (win_rate, win_loss_ratio).
        - win_rate: fraction of winning trades (0.0 to 1.0)
        - win_loss_ratio: avg_win / abs(avg_loss) if both exist, else 1.0
        """
        history = self._history[strategy]
        if not history:
            return 0.5, 1.0  # Default to 50% win rate, 1:1 ratio

        wins = [pnl for pnl, won in history if won]
        losses = [pnl for pnl, won in history if not won]

        # Win rate
        total = len(history)
        win_count = len(wins)
        W = win_count / total if total > 0 else 0.5

        # Win/loss ratio
        avg_win = sum(wins) / len(wins) if wins else 1.0
        avg_loss = abs(sum(losses) / len(losses)) if losses else 1.0
        R = avg_win / avg_loss if avg_loss > 0 else 1.0

        return W, R

    def get_kelly_pct(self, strategy: Strategy) -> float:
        """
        Calculate Kelly % using the formula:
        Kelly % = (W * (R+1) - 1) / R

        Where:
        - W = win rate (0.0 to 1.0)
        - R = win/loss ratio (e.g., 1.5 means wins are 1.5x losses)

        Returns Kelly % as a fraction (e.g., 0.25 = 25% of bankroll).
        Capped at KELLY_MAX_CAP (50%) for safety.
        """
        W, R = self.get_stats(strategy)

        # If no history (W=0 and R=0), use FIXED_KELLY_PCT as baseline (4% of bankroll per Tony's config)
        if W == 0 and R == 0:
            return FIXED_KELLY_PCT

        if R <= 0:
            return 0.0

        # Kelly formula: Kelly % = (W * (R+1) - 1) / R
        kelly_pct = (W * (R + 1) - 1) / R

        # Cap at maximum (never bet more than 50% of balance)
        kelly_pct = min(kelly_pct, KELLY_MAX_CAP)

        # If Kelly is negative or zero (e.g. W=0.5, R=1.0 → edge case no edge),
        # fall back to FIXED_KELLY_PCT instead of betting nothing
        if kelly_pct <= 0:
            kelly_pct = FIXED_KELLY_PCT

        return kelly_pct


@dataclass
class TradeSignal:
    """Represents a trading signal."""
    strategy: Strategy
    ticker: str
    side: str  # 'yes' or 'no'
    price: float  # Entry price
    size: float  # Number of contracts to buy (Tony's Fix: was dollars, now contracts)
    reason: str  # Human readable reason
    take_profit: Optional[float] = None  # For DRIFT strategies
    stop_loss: Optional[float] = None    # For DRIFT strategies
    tp_pct: Optional[float] = None       # TP percentage (deprecated - use trailing stop)
    sl_pct: Optional[float] = None        # SL percentage (deprecated - use absolute)
    scale_in_size: float = 0.0           # Additional size for scaling in (50% of initial)
    # === TONYS MOMENTUM STRATEGY: Flat 30% trailing stop everywhere (was 20%) ===
    trailing_stop_pct: float = 0.40       # 40% buffer (drop/rise from peak before exit)
    trailing_stop_trigger_pct: float = 0.30  # 30% profit before trailing stop activates
    confidence: int = 50                  # Signal confidence 0-100
    trailing_stop_buffer: float = 0.40    # 40% buffer (alias for clarity)
    max_hold_minutes: int = 10           # Dynamic based on entry zone
    use_time_scaling: bool = False        # If True, use 80%->20% time-scaled stop


@dataclass
class Position:
    """Represents an open position."""
    ticker: str
    side: str
    entry_price: float
    size: float
    open_time: float  # Unix timestamp
    strategy: Strategy
    take_profit: Optional[float] = None
    stop_loss: Optional[float] = None
    first_cross_direction: str = ""  # Tony's first crossing insight: 'up', 'down', or ''

    # === TONYS MOMENTUM STRATEGY: Flat 30% trailing stop everywhere (was 20%) ===
    trailing_stop_pct: float = 0.40       # 40% buffer (drop/rise from peak before exit)
    trailing_stop_active: bool = False   # Trailing stop activates after 50% profit
    trailing_stop_trigger_pct: float = 0.50  # 50% profit before trailing stop activates
    peak_price: float = 0.0              # Track peak price for longs, trough for shorts
    scale_in_count: int = 0              # Number of times we've scaled in
    max_scale_ins: int = 2               # Max 2 scale-ins per position
    scale_in_size: float = 0.0           # Additional size per scale-in
    unrealized_pnl: float = 0.0          # Running unrealized PnL
    avg_price: float = 0.0               # Weighted average entry price
    confidence: int = 50                 # Signal confidence 0-100 (for trailing stop logging)
    use_time_scaling: bool = False        # If True, use 80%->20% time-scaled stop

    def __post_init__(self):
        """Initialize computed fields after dataclass init."""
        if self.avg_price == 0.0:
            self.avg_price = self.entry_price
        if self.peak_price == 0.0:
            self.peak_price = self.entry_price

    def current_value(self, current_price: float) -> float:
        """Calculate current value of position."""
        if self.side == "yes":
            # Value = size * (current_price - entry_price) + size
            # When YES goes to $1, we win size; at $0, we lose size
            return self.size * current_price
        else:
            # Value = size * ((1 - current_price) - (1 - entry_price)) + size
            return self.size * (1 - current_price)

    def update_trailing_stop_confidence(self, current_price: float, confidence: int) -> bool:
        """
        Update trailing stop using instance variables (now 30% for MOMENTUM, confidence-based for DRIFT).

        TONY FIX: Only trail/exit if we're in PROFIT. If price is moving against us,
        give it room to come back instead of locking in a loss.

        Returns True if trailing stop is now active.
        """
        # Use the trailing stop values from the Position (set from TradeSignal at position creation)
        # MOMENTUM strategies: flat 30%/30%
        # DRIFT strategies: confidence-based (25%-45% buffer, 30%-60% trigger)
        ts_buffer = self.trailing_stop_pct
        ts_trigger = self.trailing_stop_trigger_pct

        if self.side == "yes":
            if current_price > self.peak_price:
                profit_pct = (current_price - self.entry_price) / self.entry_price
                # TONY FIX: Only activate trailing stop if we're actually in profit
                if profit_pct >= ts_trigger and profit_pct > 0:
                    self.trailing_stop_active = True
                    logger.info(f"{self.ticker}: CONF={confidence} Long trailing stop ACTIVE @ ${current_price:.4f}, peak=${self.peak_price:.4f}, buffer={ts_buffer:.0%}, profit={profit_pct:.2%}")
                self.peak_price = current_price
                return self.trailing_stop_active
            else:
                # TONY FIX: Only trail/exit if we're currently in profit
                if self.trailing_stop_active:
                    current_profit_pct = (current_price - self.entry_price) / self.entry_price
                    # Only exit if we're STILL in profit (price moved against us but not yet a loss)
                    if current_profit_pct > 0:
                        drop_from_peak = (self.peak_price - current_price) / self.peak_price
                        if drop_from_peak >= ts_buffer:
                            logger.info(f"{self.ticker}: CONF={confidence} Long TRAILING STOP HIT @ ${current_price:.4f} (peak=${self.peak_price:.4f}, drop={drop_from_peak:.2%}, profit={current_profit_pct:.2%})")
                            return True
        else:
            if current_price < self.peak_price or self.peak_price == 0.0:
                self.peak_price = current_price
                profit_pct = (self.entry_price - current_price) / self.entry_price
                # TONY FIX: Only activate trailing stop if we're actually in profit
                if profit_pct >= ts_trigger and profit_pct > 0:
                    self.trailing_stop_active = True
                    logger.info(f"{self.ticker}: CONF={confidence} Short trailing stop ACTIVE @ ${current_price:.4f}, trough=${self.peak_price:.4f}, buffer={ts_buffer:.0%}, profit={profit_pct:.2%}")
                return self.trailing_stop_active
            else:
                # TONY FIX: Only trail/exit if we're currently in profit
                if self.trailing_stop_active:
                    current_profit_pct = (self.entry_price - current_price) / self.entry_price
                    # Only exit if we're STILL in profit (price moved against us but not yet a loss)
                    if current_profit_pct > 0:
                        rise_from_trough = (current_price - self.peak_price) / self.peak_price
                        if rise_from_trough >= ts_buffer:
                            logger.info(f"{self.ticker}: CONF={confidence} Short TRAILING STOP HIT @ ${current_price:.4f} (trough=${self.peak_price:.4f}, rise={rise_from_trough:.2%}, profit={current_profit_pct:.2%})")
                            return True
        return False

    def update_trailing_stop(self, current_price: float) -> bool:
        """
        Update trailing stop based on current price.
        TONY FIX: Only trail/exit if we're in PROFIT. If price is moving against us,
        give it room to come back instead of locking in a loss.
        Returns True if trailing stop is now active.
        """
        if self.side == "yes":
            # For YES (long): track peak price
            if current_price > self.peak_price:
                profit_pct = (current_price - self.entry_price) / self.entry_price
                # TONY FIX: Only activate trailing stop if we're actually in profit
                if profit_pct >= self.trailing_stop_trigger_pct and profit_pct > 0:
                    self.trailing_stop_active = True
                    logger.info(f"{self.ticker}: Long trailing stop ACTIVE @ ${current_price:.4f}, peak=${self.peak_price:.4f}, profit={profit_pct:.2%}")
                self.peak_price = current_price
                return self.trailing_stop_active
            else:
                # TONY FIX: Only trail/exit if we're currently in profit
                if self.trailing_stop_active:
                    current_profit_pct = (current_price - self.entry_price) / self.entry_price
                    # Only exit if we're STILL in profit (price moved against us but not yet a loss)
                    if current_profit_pct > 0:
                        drop_from_peak = (self.peak_price - current_price) / self.peak_price
                        if drop_from_peak >= self.trailing_stop_pct:
                            logger.info(f"{self.ticker}: Long TRAILING STOP HIT @ ${current_price:.4f} (peak=${self.peak_price:.4f}, drop={drop_from_peak:.2%}, profit={current_profit_pct:.2%})")
                            return True
        else:
            # For NO (short): track trough price
            if current_price < self.peak_price or self.peak_price == 0.0:
                self.peak_price = current_price
                profit_pct = (self.entry_price - current_price) / self.entry_price
                # TONY FIX: Only activate trailing stop if we're actually in profit
                if profit_pct >= self.trailing_stop_trigger_pct and profit_pct > 0:
                    self.trailing_stop_active = True
                    logger.info(f"{self.ticker}: Short trailing stop ACTIVE @ ${current_price:.4f}, trough=${self.peak_price:.4f}, profit={profit_pct:.2%}")
                return self.trailing_stop_active
            else:
                # TONY FIX: Only trail/exit if we're currently in profit
                if self.trailing_stop_active:
                    current_profit_pct = (self.entry_price - current_price) / self.entry_price
                    # Only exit if we're STILL in profit (price moved against us but not yet a loss)
                    if current_profit_pct > 0:
                        rise_from_trough = (current_price - self.peak_price) / self.peak_price
                        if rise_from_trough >= self.trailing_stop_pct:
                            logger.info(f"{self.ticker}: Short TRAILING STOP HIT @ ${current_price:.4f} (trough=${self.peak_price:.4f}, rise={rise_from_trough:.2%}, profit={current_profit_pct:.2%})")
                            return True
        return False

    def should_scale_in(self, current_price: float) -> bool:
        """
        Check if we should scale in (add to winning position).
        Scale in every 10% increase in our direction, up to 2 scale-ins max.
        """
        if self.scale_in_count >= self.max_scale_ins:
            return False

        if self.side == "yes":
            profit_pct = (current_price - self.entry_price) / self.entry_price
            # Scale in every 10% gain (allow scaling at any profit level >= 10%)
            if profit_pct >= 0.10:
                return True
        else:
            profit_pct = (self.entry_price - current_price) / self.entry_price
            # Scale in every 10% gain
            if profit_pct >= 0.10:
                return True
        return False

    def record_scale_in(self, new_price: float, additional_size: float):
        """Record a scale-in: update average price and size."""
        total_cost = (self.size * self.avg_price) + (additional_size * new_price)
        self.size += additional_size
        self.avg_price = total_cost / self.size
        self.scale_in_count += 1
        logger.info(f"{self.ticker}: SCALED IN @ ${new_price:.4f} (+${additional_size:.2f}), new size=${self.size:.2f}, avg_price=${self.avg_price:.4f}, scale_ins={self.scale_in_count}")


class StrategyEngine:
    """Evaluates markets and generates trading signals."""

    GRACE_PERIOD_SEC = 120          # Never enter in first 2 minutes of a series

    def __init__(self, cash_available: float, api=None):
        self.cash = cash_available
        self.api = api  # Optional KalshiAPI for First Cross floor_strike fetching
        self.tracker = StrategyTracker(KELLY_TRACKED_TRADES)
        self.first_cross = FirstCrossTracker()  # YES price midpoint crossing (existing)
        self.coin_first_cross = FirstCrossCoinTracker()  # Coin price vs target crossing (new)
        self._floor_strikes: Dict[str, float] = {}  # Cache floor_strike per ticker
        self._market_open_times: Dict[str, float] = {}  # Track when each market opened (for grace period)

    def reset_cross_tracker(self, ticker: str):
        """Reset the first cross tracker for a ticker (when market expires/closes)."""
        self.first_cross.reset(ticker)
        if ticker in self._market_open_times:
            del self._market_open_times[ticker]
        if ticker in self._floor_strikes:
            del self._floor_strikes[ticker]

    def reset_series_state(self):
        """Reset state at the start of a new series (called by bot on new series)."""
        logger.info("NEW SERIES: State reset")

    def update_cash(self, cash: float):
        """Update available cash for Kelly sizing."""
        self.cash = cash

    def record_trade_result(self, strategy: Strategy, pnl: float):
        """Record a trade result for Kelly tracking."""
        self.tracker.record_trade(strategy, pnl)
        W, R = self.tracker.get_stats(strategy)
        kelly_pct = self.tracker.get_kelly_pct(strategy)
        logger.info(f"Strategy {strategy.value} stats: W={W:.2%}, R={R:.2f}x, Kelly={kelly_pct:.2%}")

    def calculate_kelly_size(self, strategy: Strategy, prob: float, confidence: int = 50, entry_price: float = 0.50) -> Tuple[float, float, int]:
        """
        Calculate Kelly Criterion bet size using historical strategy performance,
        then adjust based on CONFIDENCE MULTIPLIER (Nerd v2).

        Returns (contracts, kelly_pct, confidence) tuple.
        - contracts: number of contracts to buy (whole, capped)
        - kelly_pct: the Kelly % used (for logging)
        - confidence: the confidence score (0-100)

        CONFIDENCE MULTIPLIER (Nerd v2):
        - CONF 80+: Kelly * 1.0 (full signal, full bet)
        - CONF 60-79: Kelly * 0.75 (good signal, reduce)
        - CONF 40-59: Kelly * 0.50 (moderate signal, half bet)
        - CONF <40: Skip (weak signal, don't trade)

        Hard caps: MAX_BET = $2, MIN_BET = $0.10

        Tony's Fix: Kelly outputs fraction of bankroll to risk (e.g., 0.05 = 5%).
        We convert to contracts: dollar_amount / entry_price, rounded DOWN.
        """
        import math

        # Skip if confidence too low
        if confidence < 40:
            return 0.0, 0.0, confidence

        if prob <= 0 or prob >= 1:
            return 0.0, 0.0, confidence

        # Get Kelly % from historical performance
        kelly_pct = self.tracker.get_kelly_pct(strategy)

        # Apply confidence multiplier (Nerd v2)
        if confidence >= 80:
            conf_mult = 1.0   # Full Kelly
        elif confidence >= 60:
            conf_mult = 0.75  # Reduce by 25%
        elif confidence >= 40:
            conf_mult = 0.50  # Reduce by 50%
        else:
            conf_mult = 0.0   # Skip

        effective_pct = kelly_pct * conf_mult

        # Cap at KELLY_MAX_CAP (never more than 20% of balance on one trade)
        effective_pct = min(effective_pct, KELLY_MAX_CAP)

        # Convert to dollar amount to risk
        dollar_amount = self.cash * effective_pct

        # Clamp dollar amount to hard limits
        dollar_amount = max(MIN_BET, min(MAX_BET, dollar_amount))

        # Convert dollar amount to contracts (Tony's Fix)
        # contracts = dollar_amount / entry_price
        if entry_price > 0:
            contracts = dollar_amount / entry_price
        else:
            contracts = 0.0

        # Round UP to whole contracts (Tony: "only whole shares")
        contracts = math.ceil(contracts)

        # Cap at max_bet / entry_price
        if entry_price > 0:
            max_contracts = MAX_BET / entry_price
            contracts = min(contracts, max_contracts)

        # Minimum 0 contracts (skip if too small)
        if contracts <= 0:
            return 0.0, effective_pct, confidence

        return int(contracts), effective_pct, confidence

    def calculate_confidence(
        self,
        strategy: Strategy,
        market: 'Market',
        coin: str,
        mid_price: float,
        time_left: int
    ) -> int:
        """
        Calculate confidence score (0-100) for a potential trade.

        Factors:
        1. Signal strength (how many indicators agree) - up to 25 points
        2. Trend clarity (clean drift vs choppy) - up to 20 points
        3. Volume confirmation - up to 15 points
        4. Distance from entry to stop-loss - up to 20 points
        5. Time of day / market conditions - up to 10 points
        6. Candle drift building time - up to 10 points

        Returns confidence integer 0-100.
        """
        score = 50  # Start at neutral

        # === Factor 1: Signal Strength (up to 25 pts) ===
        # Check how many positive indicators we have
        indicators = 0

        # Coinbase bias alignment
        bias = get_coinbase_bias(coin)
        if strategy == Strategy.DRIFT_BUY and bias == 'bullish':
            indicators += 1
        elif strategy == Strategy.DRIFT_SHORT and bias == 'bearish':
            indicators += 1

        # First cross alignment
        preferred_side = self.first_cross.get_preferred_side(market.ticker)
        if strategy == Strategy.DRIFT_BUY and preferred_side == 'yes':
            indicators += 1
        elif strategy == Strategy.DRIFT_SHORT and preferred_side == 'no':
            indicators += 1
        elif strategy == Strategy.FIRST_CROSS and preferred_side:
            indicators += 1

        # Kelly historical edge (if strategy has positive track record)
        kelly_pct = self.tracker.get_kelly_pct(strategy)
        if kelly_pct > 0.1:
            indicators += 1
        if kelly_pct > 0.2:
            indicators += 1

        # Map indicators to score (0-4 indicators -> 0-25 pts)
        signal_score = min(25, indicators * 8)
        score += (signal_score - 12)  # +/- relative to neutral

        # === Factor 2: Trend Clarity (up to 20 pts) ===
        # Dead zone is bad - prices in $0.45-$0.55 are choppy
        dist_from_mid = abs(mid_price - 0.50)
        if dist_from_mid > 0.30:  # $0.20 or $0.80 - very clear trend
            trend_score = 20
        elif dist_from_mid > 0.20:  # $0.30 or $0.70 - clear
            trend_score = 15
        elif dist_from_mid > 0.10:  # $0.40 or $0.60 - moderate
            trend_score = 8
        else:  # $0.45-$0.55 - choppy dead zone
            trend_score = -5  # Penalty for being in dead zone
        score += (trend_score - 8)

        # === Factor 3: Volume Confirmation (up to 15 pts) ===
        # Strong Coinbase bias = volume is confirming direction
        if bias == 'bullish' and strategy == Strategy.DRIFT_BUY:
            volume_score = 15
        elif bias == 'bearish' and strategy == Strategy.DRIFT_SHORT:
            volume_score = 15
        elif bias == 'neutral':
            volume_score = 5
        else:
            volume_score = 0
        score += (volume_score - 5)

        # === Factor 4: Distance from Entry to Stop-Loss (up to 20 pts) ===
        # Tighter SL = higher confidence (we're wrong less often)
        # Wider SL = lower confidence (more uncertainty)
        if strategy == Strategy.DRIFT_BUY:
            sl_price = DRIFT_BUY_STOP_LOSS
            sl_distance = mid_price - sl_price
            # $0.30 entry, $0.22 SL = $0.08 risk = 21% of entry (tight = good)
            # $0.35 entry, $0.22 SL = $0.13 risk = 27% of entry (acceptable)
            sl_risk_pct = sl_distance / mid_price if mid_price > 0 else 1
        elif strategy == Strategy.DRIFT_SHORT:
            sl_price = DRIFT_SHORT_STOP_LOSS
            sl_distance = sl_price - mid_price
            sl_risk_pct = sl_distance / mid_price if mid_price > 0 else 1
        else:
            sl_risk_pct = 0.3  # Default moderate risk

        if sl_risk_pct < 0.20:  # Very tight SL
            sl_score = 20
        elif sl_risk_pct < 0.30:
            sl_score = 15
        elif sl_risk_pct < 0.40:
            sl_score = 8
        else:
            sl_score = 0
        score += (sl_score - 10)

        # === Factor 5: Time of Day / Market Conditions (up to 10 pts) ===
        # More time left = better confidence (trade has room to develop)
        # Less time = rushed, lower confidence
        if time_left >= 600:  # 10+ minutes - ideal
            time_score = 10
        elif time_left >= 300:  # 5-10 minutes - good
            time_score = 7
        elif time_left >= 180:  # 3-5 minutes - acceptable
            time_score = 4
        else:  # <3 minutes - risky
            time_score = -5
        score += (time_score - 3)

        # === Factor 6: Candle Drift Building (up to 10 pts) ===
        # If we're in a drift strategy, check if drift has been building
        # (price has been moving in our direction for multiple candles)
        if strategy in (Strategy.DRIFT_BUY, Strategy.DRIFT_SHORT):
            drift_score = 5  # Neutral - we don't have historical drift data
            # Could enhance with actual candle history if available
            score += (drift_score - 5)
        else:
            pass  # No drift adjustment for other strategies

        # === Clamp score to 0-100 ===
        confidence = max(0, min(100, int(score)))

        logger.debug(
            f"CONFIDENCE: {market.ticker} | score={score} | "
            f"signal={signal_score}/25 | trend={trend_score}/20 | "
            f"volume={volume_score}/15 | sl={sl_score}/20 | "
            f"time={time_score}/10 | CONF={confidence}"
        )

        return confidence

    def evaluate_market(self, market: Market, coin: str = None) -> Optional[TradeSignal]:
        """
        NEW SERIES STRATEGY - Grace Period Only:

        1. GRACE PERIOD: Never enter in first 2 minutes of a new series
        2. ONLY FIRST_CROSS and MOMENTUM signals
        3. ALL entry conditions must be met:
           - Price between $0.20-$0.80
           - At least 2 minutes into the series
           - Has actual Coinbase momentum (not neutral)
           - For MOMENTUM: price at extreme ($0.10 or $0.90) AND clear Coinbase bias

        Trailing Stop: Trigger 50%, Buffer 40%
        """

        # Use mid price for decision
        mid_price = (market.yes_bid + market.yes_ask) / 2
        time_left = market.time_to_expiry_sec()

        logger.debug(f"Evaluating {market.ticker}: price=${mid_price:.4f}, time_left={time_left}s")

        # === EXTRACT COIN from ticker if not provided ===
        if coin is None:
            coin = market.ticker.replace('KX', '').replace('15M', '')

        # === ENTRY PRICE FILTER: Only enter when share price is $0.20-$0.80 ===
        if not (MIN_ENTRY_PRICE <= mid_price <= MAX_ENTRY_PRICE):
            logger.debug(f"{market.ticker}: Entry price ${mid_price:.4f} outside ${MIN_ENTRY_PRICE}-${MAX_ENTRY_PRICE} range - SKIPPING")
            return None

        # === TRACK MARKET OPEN TIME for grace period ===
        if market.ticker not in self._market_open_times:
            self._market_open_times[market.ticker] = time.time()

        market_age_sec = time.time() - self._market_open_times.get(market.ticker, time.time())

        # === GRACE PERIOD: Only applies to MOMENTUM, not FIRST_CROSS ===
        # (Track market age for MOMENTUM check below)

        # === DEEP BUY: Penny odds ($0.03-$0.15) - checked independently (no grace period) ===
        deep_buy_signal = self._check_deep_buy(market, mid_price, time_left)
        if deep_buy_signal:
            return deep_buy_signal

        # === Get Coinbase bias ===
        bias = get_coinbase_bias(coin)

        # === MOMENTUM: Fire when Coinbase has strong bias AND price trending, AFTER grace period ===
        # Coinbase bias: must be bullish or bearish (not neutral)
        # Price: trending in bias direction (not at extreme required)
        # MUST be at least 2 minutes into the series (grace period)
        if bias != 'neutral' and (mid_price >= 0.20 and mid_price <= 0.80):
            # Check if price is moving in the bias direction (above midpoint for bullish, below for bearish)
            if bias == 'bullish' and mid_price >= 0.50:
                side = 'yes'
                reason_suffix = 'momentum: bullish bias + price above midpoint'
            elif bias == 'bearish' and mid_price <= 0.50:
                side = 'no'
                reason_suffix = 'momentum: bearish bias + price below midpoint'
            else:
                bias = None
            
            if bias is not None:
                # GRACE PERIOD: Skip MOMENTUM in first 2 minutes
                if market_age_sec >= self.GRACE_PERIOD_SEC:
                    confidence = 60  # Momentum confidence
                    size, kelly_pct, confidence = self.calculate_kelly_size(Strategy.MOMENTUM, mid_price, confidence, mid_price)

                    if confidence >= 40:
                        logger.info(
                            f"MOMENTUM SIGNAL: {market.ticker} | "
                            f"Side: {side} @ ${mid_price:.4f} | contracts={int(size):d} | "
                            f"CONF={confidence} | TS=30%/40% | Coinbase={bias} | age={market_age_sec:.0f}s"
                        )

                        return TradeSignal(
                            strategy=Strategy.MOMENTUM,
                            ticker=market.ticker,
                            side=side,
                            price=mid_price,
                            size=size,
                            scale_in_size=int(size * 0.5),  # Scale in: add 50% more when winning
                            reason=f"MOMENTUM: {reason_suffix}, Coinbase={bias}, CONF={confidence}, age={market_age_sec:.0f}s",
                            take_profit=0.95 if side == "yes" else 0.05,
                            stop_loss=None,
                            trailing_stop_pct=0.40,
                            trailing_stop_trigger_pct=0.30,
                            confidence=confidence,
                            trailing_stop_buffer=0.40,
                            max_hold_minutes=10,
                            use_time_scaling=True  # TIME SCALING: 80%->20%
                        )

        # === FIRST CROSS: Real cross through floor strike (not market open) ===
        # --- First Cross: Coin price vs target price ---
        if market.ticker not in self._floor_strikes:
            if self.api is not None:
                floor_strike = self.coin_first_cross.get_floor_strike(market.ticker, self.api)
                if floor_strike is not None:
                    self._floor_strikes[market.ticker] = floor_strike
                    logger.info(f"FIRST_CROSS: {market.ticker} target price set to ${floor_strike:,.2f}")

        has_coin_cross = False
        if market.ticker in self._floor_strikes and coin:
            target_price = self._floor_strikes[market.ticker]
            cross_direction = self.coin_first_cross.check_cross(market.ticker, coin, target_price, self.api)

            if cross_direction:
                has_coin_cross = True
                if cross_direction == "up":
                    side = "yes"
                    reason_suffix = "coin crossed ABOVE target"
                else:
                    side = "no"
                    reason_suffix = "coin crossed BELOW target"

                # First cross requires Coinbase momentum (not neutral) for higher confidence
                conf_boost = 10 if bias != 'neutral' else 0
                confidence = self.calculate_confidence(Strategy.FIRST_CROSS, market, coin, mid_price, time_left) + conf_boost
                prob = mid_price
                size, kelly_pct, confidence = self.calculate_kelly_size(Strategy.FIRST_CROSS, prob, confidence, prob)

                if confidence >= 40:
                    logger.info(
                        f"FIRST_CROSS SIGNAL (coin): {market.ticker} | "
                        f"Direction: {cross_direction} | Target: ${target_price:,.2f} | "
                        f"Side: {side} @ ${mid_price:.4f} | contracts={int(size):d} | CONF={confidence} | Coinbase={bias}"
                    )

                    return TradeSignal(
                        strategy=Strategy.FIRST_CROSS,
                        ticker=market.ticker,
                        side=side,
                        price=mid_price,
                        size=size,
                        scale_in_size=int(size * 0.5),  # Scale in: add 50% more when winning
                        reason=f"FIRST_CROSS: {reason_suffix}, target=${target_price:,.2f}, Coinbase={bias}, Kelly={kelly_pct:.2%}, CONF={confidence}",
                        take_profit=0.95 if side == "yes" else 0.05,
                        stop_loss=None,
                        trailing_stop_pct=0.40,
                        trailing_stop_trigger_pct=0.30,
                        confidence=confidence,
                        trailing_stop_buffer=0.40,
                        max_hold_minutes=10,
                        use_time_scaling=False  # NO TIME SCALING for FIRST_CROSS
                    )

        # --- First Cross: Midpoint crossing ---
        has_midpoint_cross = self.first_cross.has_crossed(market.ticker)
        if not has_coin_cross:
            cross_event = self.first_cross.update(market.ticker, mid_price)
            if cross_event:
                has_midpoint_cross = True

        if self.first_cross.should_wait(market.ticker, mid_price):
            logger.debug(f"FIRST_CROSS: {market.ticker} in dead zone (${mid_price:.4f}) - WAITING")
        elif has_midpoint_cross or (has_coin_cross == False and self.first_cross.get_preferred_side(market.ticker)):
            preferred_side = self.first_cross.get_preferred_side(market.ticker)
            if preferred_side:
                side = 'yes' if preferred_side == 'yes' else 'no'
                reason_suffix = 'crossed UP first' if preferred_side == 'yes' else 'crossed DOWN first'

                # First cross requires Coinbase momentum (not neutral) for higher confidence
                conf_boost = 10 if bias != 'neutral' else 0
                confidence = self.calculate_confidence(Strategy.FIRST_CROSS, market, coin, mid_price, time_left) + conf_boost
                prob = mid_price
                size, kelly_pct, confidence = self.calculate_kelly_size(Strategy.FIRST_CROSS, prob, confidence, prob)

                if confidence >= 40:
                    max_hold = 10

                    logger.info(
                        f"FIRST_CROSS SIGNAL (midpoint): {market.ticker} | "
                        f"Direction: {preferred_side} | Side: {side} @ ${mid_price:.4f} | "
                        f"contracts={int(size):d} | CONF={confidence} | TS=50%/40% | Coinbase={bias} | max_hold={max_hold}min"
                    )

                    return TradeSignal(
                        strategy=Strategy.FIRST_CROSS,
                        ticker=market.ticker,
                        side=side,
                        price=mid_price,
                        size=size,
                        scale_in_size=int(size * 0.5),  # Scale in: add 50% more when winning
                        reason=f"FIRST_CROSS: {reason_suffix}, Coinbase={bias}, CONF={confidence}, Kelly={kelly_pct:.2%}",
                        take_profit=0.95 if side == "yes" else 0.05,
                        stop_loss=None,
                        trailing_stop_pct=0.40,
                        trailing_stop_trigger_pct=0.30,
                        confidence=confidence,
                        trailing_stop_buffer=0.40,
                        max_hold_minutes=max_hold,
                        use_time_scaling=False  # NO TIME SCALING for FIRST_CROSS
                    )

        # === MOMENTUM_FORCE: Last resort - wait 60s, no cross, force entry ===
        no_cross_yet = not has_coin_cross and not has_midpoint_cross
        if no_cross_yet and market_age_sec >= 60 and bias != 'neutral' and (mid_price < 0.10 or mid_price > 0.90):
            if bias == 'bullish' and mid_price < 0.10:
                side = 'yes'
                reason_suffix = 'bullish + price above midpoint'
            elif bias == 'bearish' and mid_price <= 0.50:
                side = 'no'
                reason_suffix = 'bearish + price below midpoint'
            else:
                bias = None

            if bias is not None:
                confidence = 50
                size, kelly_pct, confidence = self.calculate_kelly_size(Strategy.MOMENTUM_FORCE, mid_price, confidence, mid_price)

                if confidence >= 40:
                    logger.info(
                        f"MOMENTUM_FORCE SIGNAL: {market.ticker} | "
                        f"Side: {side} @ ${mid_price:.4f} | contracts={int(size):d} | "
                        f"CONF={confidence} | TS=30%/40% | Coinbase={bias} | age={market_age_sec:.0f}s"
                    )

                    return TradeSignal(
                        strategy=Strategy.MOMENTUM_FORCE,
                        ticker=market.ticker,
                        side=side,
                        price=mid_price,
                        size=size,
                        scale_in_size=int(size * 0.5),  # Scale in: add 50% more when winning
                        reason=f"MOMENTUM_FORCE: {reason_suffix}, Coinbase={bias}, CONF={confidence}, age={market_age_sec:.0f}s",
                        take_profit=0.95 if side == "yes" else 0.05,
                        stop_loss=None,
                        trailing_stop_pct=0.40,
                        trailing_stop_trigger_pct=0.30,
                        confidence=confidence,
                        trailing_stop_buffer=0.40,
                        max_hold_minutes=8,
                        use_time_scaling=True  # TIME SCALING: 80%->20%
                    )

        return None

    def _estimate_ai_probability(self, market: Market, mid_price: float) -> Optional[float]:
        """
        Use Claude to estimate the true probability of a market.
        Returns None if estimation fails or is disabled.
        Only returns a value if AI_EDGE_THRESHOLD (5%) or more edge exists.
        """
        try:
            # Build context for AI estimation
            coin = market.ticker.replace('KX', '').replace('15M', '')

            prompt = f"""Estimate the true probability for this Kalshi crypto prediction market:

Market: {market.ticker}
Coin: {coin}
Current YES Price: ${mid_price:.4f} (this is the market's implied probability)
Question: Will {coin} be UP in the next 15 minutes?

Consider:
- Current market sentiment and price action
- Technical analysis factors
- The longshot bias (crowd often overbets low-prob outcomes)
- Mean reversion patterns in 15-min crypto markets

Respond with ONLY a number between 0.0 and 1.0 representing your estimated true probability.
Example responses: 0.45, 0.52, 0.68

Your estimate:"""

            # Call Claude via openclaw oracle CLI
            result = subprocess.run(
                ['oracle', '-m', 'minimax-portal/MiniMax-M2.7', prompt],
                capture_output=True,
                text=True,
                timeout=10,
                env={**os.environ, 'ORACLE_API_KEY': os.environ.get('ORACLE_API_KEY', '')}
            )

            if result.returncode == 0:
                # Parse the AI's response - extract number between 0 and 1
                output = result.stdout.strip()
                # Try to find a number in the output
                import re
                match = re.search(r'0?\.\d+', output)
                if match:
                    prob = float(match.group())
                    prob = max(0.01, min(0.99, prob))  # Clamp to valid range
                    return prob

        except Exception as e:
            logger.debug(f"AI probability estimation failed for {market.ticker}: {e}")

        return None

    def _check_deep_short(self, market: Market, mid_price: float, time_left: int) -> Optional[TradeSignal]:
        """
        DEEP SHORT: YES < $0.15 → SELL YES (fade the longshot)
        DISABLED via DEEP_SHORT_ENABLED = False (kill switch)

        Research shows low-probability outcomes are OVERBET (longshot bias).
        The crowd overvalues tiny YES positions hoping for big wins.
        We SELL YES (buy NO) to fade the crowd - collect when tails fail to deliver.

        We sell YES at low price like $0.10, betting event won't happen.
        Profit if YES stays low or goes lower. Loss if YES jumps up.
        """
        # Pixel: Kill switch - deep_short completely disabled
        if not DEEP_SHORT_ENABLED:
            return None

        if mid_price >= DEEP_SHORT_MAX_PRICE:
            return None

        if time_left < DEEP_MIN_TIME_LEFT_SEC:
            logger.debug(f"DEEP SHORT: {market.ticker} - not enough time left ({time_left}s)")
            return None

        # Calculate size using Kelly with historical strategy performance
        # For short: probability of YES going DOWN is (1 - price)
        prob = 1 - mid_price  # Probability that YES loses (we win)

        # Calculate confidence
        confidence = self.calculate_confidence(Strategy.DEEP_SHORT, market, coin, mid_price, time_left)
        size, kelly_pct, confidence = self.calculate_kelly_size(Strategy.DEEP_SHORT, prob, confidence, mid_price)

        logger.info(f"DEEP SHORT signal: {market.ticker} @ ${mid_price:.4f}, contracts={int(size):d}, Kelly={kelly_pct:.2%}, CONF={confidence}, time_left={time_left}s")

        return TradeSignal(
            strategy=Strategy.DEEP_SHORT,
            ticker=market.ticker,
            side="no",  # We SELL YES (buy NO)
            price=mid_price,
            size=size,
            reason=f"DEEP SHORT: Selling YES at ${mid_price:.4f} (< ${DEEP_SHORT_MAX_PRICE}), fading the longshot, CONF={confidence}",
            take_profit=None,  # No TP - ride to expiry
            stop_loss=None,     # No SL - ride to expiry
            confidence=confidence,
            trailing_stop_buffer=0.0,
            max_hold_minutes=15
        )

    def _check_deep_buy(self, market: Market, mid_price: float, time_left: int) -> Optional[TradeSignal]:
        """
        DEEP BUY: YES $0.03-$0.15 → buy penny odds, ride to $0.95

        Nerd's research: Markets priced at $0.03-$0.15 are penny odds that can
        jump 5-30x if the coin moves right. We buy YES cheap and hold to expiry
        or take profit at $0.95.

        Entry: $0.03 <= YES <= $0.15
        No stop-loss (binary - max loss is the price you paid)
        Take profit: $0.95 (ride to full resolution)
        Min time left: 2 minutes (need time for penny odds to play out)
        """
        if not DEEP_BUY_ENABLED:
            return None

        if not (DEEP_BUY_MIN_PRICE <= mid_price <= DEEP_BUY_MAX_PRICE):
            return None

        if time_left < 120:  # 2 min minimum for penny odds
            logger.debug(f"DEEP BUY: {market.ticker} - not enough time left ({time_left}s)")
            return None

        # Calculate size using Kelly with historical strategy performance
        prob = mid_price  # Probability of YES winning

        # Calculate confidence
        confidence = self.calculate_confidence(Strategy.DEEP_BUY, market, None, mid_price, time_left)
        size, kelly_pct, confidence = self.calculate_kelly_size(Strategy.DEEP_BUY, prob, confidence, mid_price)

        logger.info(f"DEEP BUY signal: {market.ticker} @ ${mid_price:.4f}, contracts={int(size):d}, Kelly={kelly_pct:.2%}, CONF={confidence}, time_left={time_left}s")

        return TradeSignal(
            strategy=Strategy.DEEP_BUY,
            ticker=market.ticker,
            side="yes",  # Buy YES - penny odds
            price=mid_price,
            size=size,
            reason=f"DEEP BUY: YES at ${mid_price:.4f} (penny odds ${DEEP_BUY_MIN_PRICE}-${DEEP_BUY_MAX_PRICE}), ride to ${DEEP_BUY_TP_PRICE}, CONF={confidence}",
            take_profit=DEEP_BUY_TP_PRICE,  # $0.95 target
            stop_loss=None,  # No SL - ride to expiry, max loss is the entry price
            confidence=confidence,
            trailing_stop_buffer=0.0,
            max_hold_minutes=15
        )

    def _check_drift_buy(self, market: Market, mid_price: float, time_left: int) -> Optional[TradeSignal]:
        """
        DRIFT BUY: YES $0.30-$0.35 → mean reversion, HOLD TO END, trailing stop only

        Tony's Feedback:
        - TP was too tight ($0.90) - killed winners
        - Now: NO fixed TP, use trailing stop to lock in profits
        - Scale in: add more if price moves in our direction

        SL: absolute $0.22 (tight, but not triggered unless we're wrong)
        Trailing stop: WIDENED - activates after 30% profit, locks in 25% from peak (was 20%/15%)
        Entry zone tightened to $0.30-$0.35 (was $0.30-$0.38) for higher conviction setups only
        """
        # Skip dead zone ($0.45-$0.55)
        if DEAD_ZONE_MIN <= mid_price <= DEAD_ZONE_MAX:
            return None

        if not (DRIFT_BUY_MIN_PRICE <= mid_price <= DRIFT_BUY_MAX_PRICE):
            return None

        if time_left < DRIFT_MIN_TIME_LEFT_SEC:
            logger.debug(f"DRIFT BUY: {market.ticker} - not enough time left ({time_left}s)")
            return None

        # FIRST CROSS FILTER: If price crossed DOWN first, momentum is bearish
        # Drift_buy (betting YES goes up) contradicts the first cross direction
        preferred_side = self.first_cross.get_preferred_side(market.ticker)
        if preferred_side == 'down':
            logger.info(f"DRIFT BUY: {market.ticker} - SKIP: price crossed DOWN first, bearish momentum contradicts drift_buy")
            return None

        # Integrate Coinbase bias - use as signal boost, not a filter
        coin = market.ticker.replace('KX', '').replace('15M', '')
        bias = get_coinbase_bias(coin)
        if bias == 'bearish':
            logger.debug(f"DRIFT BUY: {market.ticker} - Coinbase bias={bias}, using as signal boost only")

        # Calculate size using Kelly with historical strategy performance
        prob = mid_price

        # Calculate confidence score
        confidence = self.calculate_confidence(Strategy.DRIFT_BUY, market, coin, mid_price, time_left)
        size, kelly_pct, confidence = self.calculate_kelly_size(Strategy.DRIFT_BUY, prob, confidence, mid_price)

        # Calculate SL only (NO tight TP anymore)
        # Let winners run to $0.95 or trailing stop
        sl_price = DRIFT_BUY_STOP_LOSS  # $0.22 absolute

        # Scale-in size: 50% of original contracts (whole contracts only)
        scale_in_size = int(size * 0.5)

        # Confidence-based trailing stop buffer (wider for high confidence - Tony: let winners run!)
        if confidence >= 96:
            ts_buffer = 0.45
            ts_trigger = 0.60
        elif confidence >= 81:
            ts_buffer = 0.40
            ts_trigger = 0.50
        elif confidence >= 61:
            ts_buffer = 0.35
            ts_trigger = 0.40
        elif confidence >= 31:
            ts_buffer = 0.30
            ts_trigger = 0.35
        else:
            ts_buffer = 0.25
            ts_trigger = 0.30

        # Max hold time based on confidence
        max_hold = 15 if confidence >= 61 else 10 if confidence >= 31 else 8

        logger.info(f"DRIFT BUY signal: {market.ticker} @ ${mid_price:.4f}, contracts={int(size):d}, Kelly={kelly_pct:.2%}, CONF={confidence}, SL=${sl_price:.4f}, TS={ts_buffer:.0%}buffer/{ts_trigger:.0%}trigger, Coinbase={bias}, first_cross={preferred_side or 'none'}")

        return TradeSignal(
            strategy=Strategy.DRIFT_BUY,
            ticker=market.ticker,
            side="yes",
            price=mid_price,
            size=size,
            reason=f"DRIFT BUY: YES at ${mid_price:.4f} (mean reversion), CONF={confidence}, NO FIXED TP - trailing stop only, SL ${sl_price:.2f}, TS={ts_buffer:.0%}buf/{ts_trigger:.0%}trig, scale_in={int(scale_in_size):d}ct, Coinbase={bias}, first_cross={preferred_side}",
            take_profit=0.95,  # Loose TP - only exit if REALLY close to max
            stop_loss=sl_price,
            tp_pct=None,  # No percentage-based TP
            sl_pct=None,
            trailing_stop_pct=ts_buffer,
            trailing_stop_trigger_pct=ts_trigger,
            confidence=confidence,
            trailing_stop_buffer=ts_buffer,
            max_hold_minutes=max_hold
        )

    def _check_drift_short(self, market: Market, mid_price: float, time_left: int) -> Optional[TradeSignal]:
        """
        DRIFT SHORT: YES $0.57-$0.62 → sell overpriced, HOLD TO END, trailing stop only
        This means we're SELLING YES (betting it will go down)

        Tony's Feedback:
        - TP was too tight (20% gain) - killed winners
        - Now: NO fixed TP, use trailing stop to lock in profits
        - Scale in: add more if price moves in our direction

        SL: absolute $0.75 (tight, but not triggered unless we're wrong)
        Trailing stop: WIDENED - activates after 30% profit, locks in 25% from trough (was 20%/15%)
        Entry zone tightened to $0.57-$0.62 (was $0.55-$0.62) for higher conviction only
        Dead zone: no trades $0.45-$0.55
        """
        # Skip dead zone ($0.45-$0.55)
        if DEAD_ZONE_MIN <= mid_price <= DEAD_ZONE_MAX:
            return None

        if not (DRIFT_SHORT_MIN_PRICE <= mid_price <= DRIFT_SHORT_MAX_PRICE):
            return None

        if time_left < DRIFT_MIN_TIME_LEFT_SEC:
            logger.debug(f"DRIFT SHORT: {market.ticker} - not enough time left ({time_left}s)")
            return None

        # FIRST CROSS FILTER: If price crossed UP first, momentum is bullish
        # Drift_short (betting YES goes down) contradicts the first cross direction
        preferred_side = self.first_cross.get_preferred_side(market.ticker)
        if preferred_side == 'up':
            logger.info(f"DRIFT SHORT: {market.ticker} - SKIP: price crossed UP first, bullish momentum contradicts drift_short")
            return None

        # For short, probability of YES going DOWN is (1 - price)
        prob = 1 - mid_price

        # Extract coin from ticker for Coinbase bias
        coin = market.ticker.replace('KX', '').replace('15M', '')

        # Calculate confidence score
        confidence = self.calculate_confidence(Strategy.DRIFT_SHORT, market, coin, mid_price, time_left)
        size, kelly_pct, confidence = self.calculate_kelly_size(Strategy.DRIFT_SHORT, prob, confidence, mid_price)

        # SL only - no tight TP
        sl_price = DRIFT_SHORT_STOP_LOSS  # $0.75 absolute

        # Scale-in size: 50% of original contracts (whole contracts only)
        scale_in_size = int(size * 0.5)

        # Confidence-based trailing stop buffer (wider for high confidence - Tony: let winners run!)
        if confidence >= 96:
            ts_buffer = 0.45
            ts_trigger = 0.60
        elif confidence >= 81:
            ts_buffer = 0.40
            ts_trigger = 0.50
        elif confidence >= 61:
            ts_buffer = 0.35
            ts_trigger = 0.40
        elif confidence >= 31:
            ts_buffer = 0.30
            ts_trigger = 0.35
        else:
            ts_buffer = 0.25
            ts_trigger = 0.30

        # Max hold time based on confidence
        max_hold = 15 if confidence >= 61 else 10 if confidence >= 31 else 8

        logger.info(f"DRIFT SHORT signal: {market.ticker} @ ${mid_price:.4f}, contracts={int(size):d}, Kelly={kelly_pct:.2%}, CONF={confidence}, SL=${sl_price:.4f}, TS={ts_buffer:.0%}buffer/{ts_trigger:.0%}trigger, first_cross={preferred_side or 'none'}")

        return TradeSignal(
            strategy=Strategy.DRIFT_SHORT,
            ticker=market.ticker,
            side="no",  # We SELL YES (buy NO)
            price=mid_price,
            size=size,
            reason=f"DRIFT SHORT: Selling YES at ${mid_price:.4f} (overpriced), CONF={confidence}, NO FIXED TP - trailing stop only, SL ${sl_price:.4f}, TS={ts_buffer:.0%}buf/{ts_trigger:.0%}trig, scale_in={int(scale_in_size):d}ct",
            take_profit=0.05,  # Loose TP - only exit if REALLY close to max ($0.05 = near zero)
            stop_loss=sl_price,
            tp_pct=None,
            sl_pct=None,
            trailing_stop_pct=ts_buffer,
            trailing_stop_trigger_pct=ts_trigger,
            confidence=confidence,
            trailing_stop_buffer=ts_buffer,
            max_hold_minutes=max_hold
        )

    def check_position_exit(self, position: Position, current_price: float, time_left: int) -> Tuple[bool, str]:
        """
        TONY'S TIME-SCALED TWO-STAGE STOP SYSTEM:

        Stage 1: TIME-SCALED STATIC STOP (80% at open → 20% at close)
        - Linear interpolation over 15 minutes
        - Gives early entries room to breathe

        Stage 2: TRAILING STOP (after +30% profit, 40% buffer)
        - After price moves WITH us by 30%, trail from there

        Returns (should_exit, reason).
        """
        # BUG FIX: Skip exit checks for positions with 0 contracts
        if position.size <= 0:
            return False, ""
        if position.strategy == Strategy.DEEP_SHORT:
            return False, ""

        entry_price = position.entry_price

        # === TIME-SCALED STOP CALCULATION (only for MOMENTUM/MOMENTUM_FORCE) ===
        time_elapsed_sec = time.time() - position.open_time
        time_elapsed_min = time_elapsed_sec / 60.0

        # Check if this strategy uses time scaling
        use_time_scale = getattr(position, 'use_time_scaling', False)

        if use_time_scale:
            # Linear interpolation: 80% at open → 20% at close (15 min)
            stop_pct = INITIAL_STOP_PCT - (time_elapsed_sec / MARKET_DURATION_SEC) * (INITIAL_STOP_PCT - FINAL_STOP_PCT)
            stop_pct = max(stop_pct, FINAL_STOP_PCT)  # Never tighter than final
            # In final 3 min, enforce minimum 30% stop (prevent choppage)
            if time_left <= 180:
                stop_pct = max(stop_pct, MIN_STOP_PCT)
        else:
            # Static -30% stop for FIRST_CROSS
            stop_pct = 0.30

        # === NEAR-EXPIRY EXIT (last 60 seconds) ===
        if time_left <= 60:
            logger.info(f"{position.ticker}: Near expiry ({time_left}s) - closing position")
            return True, f"Expiry: closing at ${current_price:.4f}"

        # === TONY'S TWO-STAGE STOP SYSTEM ===

        if position.side == "yes":
            # YES: We profit when price goes UP

            # Stage 1: STATIC STOP
            static_stop_price = entry_price * (1 - stop_pct)
            if current_price <= static_stop_price:
                loss_pct = (entry_price - current_price) / entry_price
                stop_label = "TIME-SCALED STOP" if use_time_scale else "STATIC STOP"
                logger.info(f"{position.ticker}: {stop_label} HIT @ ${current_price:.4f} (entry=${entry_price:.4f}, stop={stop_pct:.0%}, loss={loss_pct:.1%}, age={time_elapsed_min:.1f}min)")
                return True, f"{stop_label}: -{stop_pct:.0%} loss locked in"

            # Stage 2: TRAILING STOP (after +30% profit)
            profit_target_price = entry_price * (1 + TRAILING_TRIGGER_PCT)

            if not position.trailing_stop_active and current_price >= profit_target_price:
                position.trailing_stop_active = True
                position.peak_price = current_price
                profit_pct = (current_price - entry_price) / entry_price
                logger.info(f"{position.ticker}: TRAILING STOP ACTIVATED @ ${current_price:.4f} (entry=${entry_price:.4f}, profit={profit_pct:.1%})")

            if position.trailing_stop_active:
                if current_price > position.peak_price:
                    position.peak_price = current_price
                else:
                    drop_from_peak = (position.peak_price - current_price) / position.peak_price
                    if drop_from_peak >= TRAILING_BUFFER_PCT:
                        current_profit_pct = (current_price - entry_price) / entry_price
                        logger.info(f"{position.ticker}: TRAILING STOP HIT @ ${current_price:.4f} (peak=${position.peak_price:.4f}, drop={drop_from_peak:.1%}, locked={current_profit_pct:.1%})")
                        return True, f"TRAILING STOP: locked in profits"

        else:
            # NO: We profit when price goes DOWN

            # Stage 1: STATIC STOP
            static_stop_price = entry_price * (1 + stop_pct)
            if current_price >= static_stop_price:
                loss_pct = (current_price - entry_price) / entry_price
                stop_label = "TIME-SCALED STOP" if use_time_scale else "STATIC STOP"
                logger.info(f"{position.ticker}: {stop_label} HIT @ ${current_price:.4f} (entry=${entry_price:.4f}, stop={stop_pct:.0%}, loss={loss_pct:.1%}, age={time_elapsed_min:.1f}min)")
                return True, f"{stop_label}: -{stop_pct:.0%} loss locked in"

            # Stage 2: TRAILING STOP (after +30% profit)
            profit_target_price = entry_price * (1 - TRAILING_TRIGGER_PCT)

            if not position.trailing_stop_active and current_price <= profit_target_price:
                position.trailing_stop_active = True
                position.peak_price = current_price

            if position.trailing_stop_active:
                if current_price < position.peak_price:
                    position.peak_price = current_price
                else:
                    rise_from_trough = (current_price - position.peak_price) / position.peak_price
                    if rise_from_trough >= TRAILING_BUFFER_PCT:
                        current_profit_pct = (entry_price - current_price) / entry_price
                        logger.info(f"{position.ticker}: TRAILING STOP HIT @ ${current_price:.4f} (trough=${position.peak_price:.4f}, rise={rise_from_trough:.1%}, locked={current_profit_pct:.1%})")
                        return True, f"TRAILING STOP: locked in profits"

        # === MAX HOLD TIME ===
        max_hold_minutes = 12
        if time_elapsed_sec / 60.0 >= max_hold_minutes:
            logger.info(f"{position.ticker}: Max hold time ({max_hold_minutes}min) reached")
            return True, f"Max hold: {max_hold_minutes}min"

        return False, ""
        hold_time_sec = time.time() - position.open_time
        hold_time_min = hold_time_sec / 60

        if hold_time_min > max_hold_minutes:
            logger.info(f"{position.ticker}: Max hold time exceeded ({hold_time_min:.1f}min > {max_hold_minutes}min) - closing")
            return True, f"Max hold time: {hold_time_min:.1f}min > {max_hold_minutes}min"

        # === NEAR-MAX PROFIT EXIT ===
        if position.take_profit is not None:
            if position.side == "yes" and current_price >= 0.95:
                return True, f"Near-max TP: ${current_price:.4f} >= $0.95"
            if position.side == "no" and current_price <= 0.05:
                return True, f"Near-max TP: ${current_price:.4f} <= $0.05"

        return False, ""
