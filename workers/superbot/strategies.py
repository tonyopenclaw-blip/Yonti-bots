from pathlib import Path
import time
import datetime
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

# === STRATEGY TIME ROUTING ===
# 00:00-07:59 UTC: Off-hours = MOMENTUM time (US night)
# 08:00-23:59 UTC: US hours = FIRST_CROSS time

def get_strategy_mode():
    """Returns which strategy mode is active based on UTC time.
    Returns 'momentum' for 00:00-07:59 UTC, 'first_cross' for 08:00-23:59 UTC.
    """
    current_hour_utc = datetime.datetime.utcnow().hour
    is_off_hours = current_hour_utc < 8
    mode = 'momentum' if is_off_hours else 'first_cross'
    logger.info(f"[STRATEGY ROUTING] UTC={current_hour_utc:02d}:00 | Mode={mode.upper()} | {'Momentum ACTIVE, First_Cross DISABLED' if is_off_hours else 'First_Cross ACTIVE, Momentum DISABLED'}")
    return mode

def is_first_cross_enabled():
    """Returns True if First Cross strategy should run (US hours 08-23 UTC)."""
    return not is_off_hours()

def is_off_hours():
    """Returns True if current UTC hour is 0-7 (off-hours = momentum time)."""
    return datetime.datetime.utcnow().hour < 8

def is_momentum_enabled():
    """Returns True if Momentum strategy should run (off-hours 00-07 UTC)."""
    return datetime.datetime.utcnow().hour < 8

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
# STOPS DISABLED per Nerd's production analysis (2026-04-06)
# Bot was cutting positions 38-49% loss BEFORE settlement when they would have won
# Let positions ride to settlement only. NO stops, NO less coins.
INITIAL_STOP_PCT = 0.0        # DISABLED - was 50%, positions were stopped out before winning
FINAL_STOP_PCT = 0.0          # DISABLED - was 20%
MARKET_DURATION_SEC = 900     # 15 minutes
TRAILING_TRIGGER_PCT = 0.30  # Keep trailing for winners (only after +30% profit)
TRAILING_BUFFER_PCT = 0.40   # 40% buffer from peak
MIN_STOP_PCT = 0.0            # DISABLED - was 30%
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
    MEAN_REV = "mean_rev"          # NEW: Mean reversion - buy dip / sell rip
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


class MomentumTracker:
    """
    Tracks momentum confirmation at midpoint ($0.50) for entry signals.
    Tony's Momentum Strategy (replaces MeanRevTracker):

    Entry:
    - YES: price crosses midpoint ($0.50) going UP → buy YES
    - NO: price crosses midpoint ($0.50) going DOWN → buy NO (ONLY if candle signal agrees)
    - Only enter when momentum is confirmed, not at extremes

    Exit:
    - Take profit at $0.70+
    - Stop loss at $0.30

    Confidence based on how far past midpoint (deeper = higher confidence).
    Scale-in on winning trades only at confidence tiers:
    - 70-79%: +1 contract
    - 80-89%: +2 contracts
    - 90%+: +2 contracts + 50% size boost

    Max 3 contracts per side per coin.

    FIX 2026-04-11: Momentum NO entries now REQUIRE candle signal confirmation.
    A momentum NO will only fire if there was a recent (<120s) candle NO signal.
    This prevents momentum NO entries that contradict candle YES direction.
    """

    # Signal fresh window (2 min - must match candle_watcher max age)
    CANDLE_SIGNAL_FRESH_SEC = 120
    CANDLE_SIGNALS_DIR = Path(__file__).parent / "candle_signals"
    MIDPOINT = 0.50
    TP_PRICE = 0.70  # Take profit at $0.70+
    SL_PRICE = 0.30  # Stop loss at $0.30
    MAX_CONTRACTS_PER_SIDE = 2  # Max 2 contracts per side per coin (with scale-ins up to 3)

    def __init__(self):
        # Per-ticker state: ticker -> {
        #   'crossed': bool, 'direction': str, 'prev_price': float,
        #   'entry_price': float, 'signal_fired': bool
        # }
        self._crossings: Dict[str, Dict] = {}

    def update(self, ticker: str, current_price: float) -> Optional['TradeSignal']:
        """
        Check for midpoint crossing and fire momentum signal.
        Returns TradeSignal if crossing just happened, else None.
        Only fires once per cross direction per ticker.
        """
        if ticker not in self._crossings:
            self._crossings[ticker] = {
                'crossed': False,
                'direction': None,
                'prev_price': current_price,
                'entry_price': 0.0,
                'signal_fired': False,
            }
            return None

        state = self._crossings[ticker]
        
        # Already crossed - don't fire again
        if state['crossed']:
            return None

        prev_price = state['prev_price']
        state['prev_price'] = current_price

        # Detect crossing through midpoint
        crossed_up = prev_price < self.MIDPOINT <= current_price
        crossed_down = prev_price > self.MIDPOINT >= current_price

        if not crossed_up and not crossed_down:
            return None

        # Determine direction and side
        if crossed_up:
            direction = 'up'
            side = 'yes'
            reason = f"momentum: crossed UP through ${self.MIDPOINT:.2f}"
        else:
            direction = 'down'
            side = 'no'
            reason = f"momentum: crossed DOWN through ${self.MIDPOINT:.2f}"

        # FIX 2026-04-11: Momentum NO entries REQUIRE candle signal confirmation
        # If this is a NO momentum entry, check for recent candle NO signal
        # If there's no recent candle NO signal, skip the momentum NO entry entirely
        if side == 'no':
            coin = ticker.replace('KX', '').replace('15M', '')
            if not self._has_candle_no_signal(coin):
                logger.info(f"MOMENTUM: {ticker} crossed DOWN but BLOCKED - no recent candle NO signal for {coin} (momentum NO requires candle confirmation)")
                # Mark as crossed so we don't re-check this candle
                state['crossed'] = True
                state['direction'] = direction
                state['entry_price'] = current_price
                return None
            else:
                logger.info(f"MOMENTUM: {ticker} crossed DOWN - candle NO signal confirmed for {coin}, allowing NO entry")

        # Mark as crossed (only fire once per direction)
        state['crossed'] = True
        state['direction'] = direction
        state['entry_price'] = current_price

        # Calculate confidence based on distance past midpoint
        distance_past = abs(current_price - self.MIDPOINT)
        
        if distance_past >= 0.25:  # >= $0.75 or <= $0.25
            confidence = 95
        elif distance_past >= 0.20:  # >= $0.70 or <= $0.30
            confidence = 88
        elif distance_past >= 0.15:  # >= $0.65 or <= $0.35
            confidence = 82
        elif distance_past >= 0.10:  # >= $0.60 or <= $0.40
            confidence = 72
        else:  # close to midpoint
            confidence = 65

        logger.info(
            f"MOMENTUM: {ticker} crossed {direction} @ ${current_price:.4f} "
            f"(prev=${prev_price:.4f}) -> {side.upper()} signal, CONF={confidence}"
        )

        # Create trade signal
        signal = TradeSignal(
            strategy=Strategy.MOMENTUM,  # Primary strategy
            ticker=ticker,
            side=side,
            direction='buy',
            price=current_price,
            size=1.0,  # Placeholder - StrategyEngine will calculate Kelly size
            reason=f"MOMENTUM: {reason}, distance=${distance_past:.4f}",
            take_profit=self.TP_PRICE,
            stop_loss=self.SL_PRICE,
            confidence=confidence,
            trailing_stop_pct=0.40,
            trailing_stop_trigger_pct=0.30,
            trailing_stop_buffer=0.40,
            max_hold_minutes=15,
            use_time_scaling=False,
        )
        
        return signal

    def _has_candle_no_signal(self, coin: str) -> bool:
        """
        Check if there's a fresh (<120s) candle NO signal for the given coin.
        This is used to confirm momentum NO entries - momentum NO should only fire
        when the candle watcher has also generated a NO signal for the same coin.
        """
        try:
            import json
            from datetime import datetime
            signal_file = self.CANDLE_SIGNALS_DIR / f"{coin.upper()}.json"
            if not signal_file.exists():
                return False
            with open(signal_file, 'r') as f:
                signal_data = json.load(f)
            
            # Check if it's a NO signal
            side = signal_data.get('side', '').upper()
            if side != 'NO':
                return False
            
            # Check timestamp is fresh (within CANDLE_SIGNAL_FRESH_SEC)
            ts_str = signal_data.get('timestamp', '')
            if ts_str:
                signal_time = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                if signal_time.tzinfo is None:
                    signal_time = signal_time.replace(tzinfo=None)
                age_sec = (datetime.utcnow() - signal_time).total_seconds()
                if age_sec > self.CANDLE_SIGNAL_FRESH_SEC:
                    return False
            
            return True
        except Exception as e:
            logger.debug(f"Error checking candle NO signal for {coin}: {e}")
            return False

    def has_crossed(self, ticker: str) -> bool:
        """Check if ticker has crossed the midpoint."""
        return self._crossings.get(ticker, {}).get('crossed', False)

    def get_direction(self, ticker: str) -> Optional[str]:
        """Get the cross direction for a ticker."""
        return self._crossings.get(ticker, {}).get('direction')

    def get_entry_price(self, ticker: str) -> float:
        """Get the entry price for a ticker."""
        return self._crossings.get(ticker, {}).get('entry_price', 0.0)

    def reset(self, ticker: str):
        """Reset crossing state for a ticker (e.g., when market expires)."""
        if ticker in self._crossings:
            del self._crossings[ticker]


class CandleDurationTracker:
    """
    Tracks candle time-above-prev-close percentage for Nerd's signal (FIXED).
    
    Nerd's Analysis: if price is above the previous candle's close for >90% 
    of the current 15-min candle → 98.8% (ETH) or 98.7% (SOL) win rate.
    
    FIXED Implementation (2026-04-10):
    1. Track the price at the START of each candle (open price)
    2. Continuously measure what % of the candle time the current price is ABOVE that candle's open
    3. When a new candle STARTS (market ID changes), analyze the COMPLETED candle
    4. Only fire signal at the START of a new candle (within 2 min), based on COMPLETED candle's stats
    5. Entry price must be <= $0.85
    
    Entry (only at candle CLOSE or within 2 min of new candle):
    - BUY YES when >90% above previous close for the full candle AND entry price <= $0.85
    - BUY NO when <40% above previous close
    
    Exit:
    - Hold to expiry - NO stop-loss, NO take-profit for candle-duration positions
    - The 3-min rule ($0.97/$0.01) still applies ONLY for non-candle-duration positions
    
    Coin filter:
    - Only trade ETH and SOL for candle-duration (98.8% and 98.7% win rates)
    - All other coins: use regular momentum strategy with lower confidence
    
    Scale-ins:
    - Only scale in on candle-duration positions at EXTREME zones (≤$0.30 or ≥$0.70) when winning
    - Never scale in at midpoint
    """

    # Coin filter: only ETH and SOL for candle-duration
    CANDLE_DURATION_COINS = {'BTC', 'ETH', 'BNB', 'SOL', 'DOGE', 'XRP', 'HYPE', 'ADA'}
    
    # Entry price must be <= $0.85
    MAX_ENTRY_PRICE = 0.85
    
    # Thresholds for completed candle analysis
    BULLISH_THRESHOLD = 0.90  # >90% above previous close = BUY YES
    BEARISH_THRESHOLD = 0.40  # <40% above previous close = BUY NO

    def __init__(self):
        # Per-ticker state: ticker -> {
        #   'candle_open_price': float,
        #   'candle_start_time': float,
        #   'prev_close': float,  # Previous candle's close price
        #   'samples_above': list of (timestamp, price),
        #   'samples_below': list of (timestamp, price),
        #   'signal_fired': bool
        # }
        self._candles: Dict[str, Dict] = {}
        self._prev_ticker: Optional[str] = None
        # Store completed candle analysis: ticker -> {above_pct, side, confidence}
        self._completed_analysis: Dict[str, Dict] = {}
        # Track if we've fired a pending signal for a completed candle
        self._pending_signal_fired: Dict[str, bool] = {}

    def update(self, ticker: str, current_price: float, coin: str = None) -> Optional['TradeSignal']:
        """
        Update candle tracking and check for signals.
        
        Signals only fire at the START of a new candle (when market ID changes),
        based on the COMPLETED candle's stats.
        
        Args:
            ticker: Current market ticker
            current_price: Current market price
            coin: Coin name (ETH, SOL, etc.) - required for coin filtering
            
        Returns TradeSignal if crossing just happened, else None.
        """
        current_time = time.time()
        
        # Detect new candle (new ticker = new market = new candle started)
        if self._prev_ticker is not None and ticker != self._prev_ticker:
            # New candle started - analyze the COMPLETED candle
            completed_ticker = self._prev_ticker
            if completed_ticker in self._candles:
                self._analyze_completed_candle(completed_ticker)
            # Initialize new candle tracking
            if ticker in self._candles:
                del self._candles[ticker]
            # Reset pending signal fired for new candle
            self._pending_signal_fired[ticker] = False
        
        self._prev_ticker = ticker
        
        # Initialize new candle tracking
        if ticker not in self._candles:
            self._candles[ticker] = {
                'candle_open_price': current_price,
                'candle_start_time': current_time,
                'prev_close': current_price,  # Will be updated as we track
                'samples_above': [],
                'samples_below': [],
                'signal_fired': False,
            }
            logger.debug(f"CANDLE_DURATION: New candle started {ticker} @ ${current_price:.4f}")
            
            # Check if we have a pending signal from the completed candle
            if ticker in self._completed_analysis and not self._pending_signal_fired.get(ticker, False):
                analysis = self._completed_analysis[ticker]
                # Only fire if entry price is <= $0.85
                if current_price <= self.MAX_ENTRY_PRICE:
                    # Check coin filter - only ETH and SOL for candle-duration
                    if coin and coin.upper() in self.CANDLE_DURATION_COINS:
                        self._pending_signal_fired[ticker] = True
                        logger.info(
                            f"CANDLE_DURATION: {ticker} @ ${current_price:.4f} | "
                            f"Completed candle above_pct={analysis['above_pct']:.1%} -> "
                            f"BUY {analysis['side'].upper()}, CONF={analysis['confidence']} "
                            f"(from completed candle analysis)"
                        )
                        return TradeSignal(
                            strategy=Strategy.MOMENTUM,
                            ticker=ticker,
                            side=analysis['side'],
                            direction='buy',
                            price=current_price,
                            size=1.0,
                            reason=f"CANDLE_DURATION: completed candle was above prev_close {analysis['above_pct']:.1%}, {analysis['side']}",
                            take_profit=None,  # NO TP for candle-duration
                            stop_loss=None,    # NO SL for candle-duration
                            confidence=analysis['confidence'],
                            trailing_stop_pct=0.40,
                            trailing_stop_trigger_pct=0.30,
                            trailing_stop_buffer=0.40,
                            max_hold_minutes=15,
                            use_time_scaling=False,
                            is_candle_duration=True,  # Flag for superbot
                        )
                    else:
                        logger.debug(f"CANDLE_DURATION: Skipping {coin} - not ETH/SOL (candle-duration requires ETH/SOL)")
                else:
                    logger.info(f"CANDLE_DURATION: Entry price ${current_price:.4f} > $0.85 - not firing candle-duration signal")
            return None
        
        candle = self._candles[ticker]
        candle_open = candle['candle_open_price']
        candle_start = candle['candle_start_time']
        
        # Track sample: above or below candle open
        if current_price > candle_open:
            candle['samples_above'].append((current_time, current_price))
        else:
            candle['samples_below'].append((current_time, current_price))
        
        # Update prev_close to be the last sample price (close of completed candle)
        all_samples = candle['samples_above'] + candle['samples_below']
        if all_samples:
            candle['prev_close'] = all_samples[-1][1]
        
        return None

    def _analyze_completed_candle(self, ticker: str) -> None:
        """
        Analyze a completed candle when a new one starts.
        Store the analysis for when the new candle starts (within 2 min).
        
        Nerd's signal: if price was above candle open for >90% of the candle,
        there's a 98.8% (ETH) or 98.7% (SOL) chance of ending YES.
        """
        if ticker not in self._candles:
            return
        
        candle = self._candles[ticker]
        above_count = len(candle['samples_above'])
        below_count = len(candle['samples_below'])
        total_samples = above_count + below_count
        
        if total_samples < 2:
            logger.debug(f"CANDLE_DURATION: {ticker} - insufficient samples ({total_samples}) for analysis")
            return
        
        above_pct = above_count / total_samples
        
        # Determine signal based on thresholds
        if above_pct > self.BULLISH_THRESHOLD:
            confidence = self._get_confidence(above_pct)
            self._completed_analysis[ticker] = {
                'above_pct': above_pct,
                'side': 'yes',
                'confidence': confidence
            }
            logger.info(
                f"CANDLE_DURATION COMPLETED: {ticker} | "
                f"Was above open {above_pct:.1%} (>90% threshold) -> PENDING BUY YES, CONF={confidence}"
            )
        elif above_pct < self.BEARISH_THRESHOLD:
            self._completed_analysis[ticker] = {
                'above_pct': above_pct,
                'side': 'no',
                'confidence': 80  # Bearish confidence
            }
            logger.info(
                f"CANDLE_DURATION COMPLETED: {ticker} | "
                f"Was above open {above_pct:.1%} (<40% threshold) -> PENDING BUY NO, CONF=80"
            )
        else:
            logger.debug(
                f"CANDLE_DURATION COMPLETED: {ticker} | "
                f"Above open {above_pct:.1%} - no signal (threshold not met)"
            )

    def _get_confidence(self, above_pct: float) -> int:
        """Get confidence based on percentage above candle open.
        
        Nerd's analysis shows:
        - ETH: 98.8% win rate when >90% above previous close
        - SOL: 98.7% win rate when >90% above previous close
        """
        if above_pct > 0.95:
            return 98  # Near-perfect - use ETH/SOL win rate
        elif above_pct > 0.90:
            return 95  # Strong momentum
        elif above_pct > 0.80:
            return 80
        elif above_pct > 0.70:
            return 70
        else:
            return 50

    def get_above_pct(self, ticker: str) -> float:
        """Get the current percentage above candle open for a ticker."""
        if ticker not in self._candles:
            return 0.5
        candle = self._candles[ticker]
        above_count = len(candle['samples_above'])
        below_count = len(candle['samples_below'])
        total = above_count + below_count
        if total < 2:
            return 0.5
        return above_count / total

    def reset(self, ticker: str):
        """Reset candle state for a ticker."""
        if ticker in self._candles:
            del self._candles[ticker]
        if ticker in self._completed_analysis:
            del self._completed_analysis[ticker]
        if ticker in self._pending_signal_fired:
            del self._pending_signal_fired[ticker]


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
            Strategy.MEAN_REV: deque(maxlen=tracked_trades),
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
    direction: str  # 'buy' or 'sell' - Tony's two-way market making
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
    is_candle_duration: bool = False      # True if this is a candle-duration signal (no SL/TP)


@dataclass
class Position:
    """Represents an open position."""
    ticker: str
    side: str  # 'yes' or 'no'
    entry_price: float
    size: float
    open_time: float  # Unix timestamp
    strategy: Strategy
    direction: str = "buy"  # 'buy' or 'sell' - Tony's two-way market making (default 'buy' for backwards compat)
    take_profit: Optional[float] = None
    stop_loss: Optional[float] = None
    first_cross_direction: str = ""  # Tony's first crossing insight: 'up', 'down', or ''

    # === TONYS MOMENTUM STRATEGY: Flat 30% trailing stop everywhere (was 20%) ===
    trailing_stop_pct: float = 0.40       # 40% buffer (drop/rise from peak before exit)
    trailing_stop_active: bool = False   # Trailing stop activates after 50% profit
    trailing_stop_trigger_pct: float = 0.50  # 50% profit before trailing stop activates
    peak_price: float = 0.0              # Track peak price for longs, trough for shorts
    scale_in_count: int = 0              # Number of times we've scaled in
    max_scale_ins: int = 2               # Max 2 scale-ins allowed (max 3 contracts total)
    scale_in_size: float = 0.0           # Additional size per scale-in (calculated on scale-in)
    unrealized_pnl: float = 0.0          # Running unrealized PnL
    avg_price: float = 0.0               # Weighted average entry price
    confidence: int = 50                 # Signal confidence 0-100 (for trailing stop logging)
    entry_confidence: int = 0            # Entry confidence 0-100 (stored for scale-in decisions)
    use_time_scaling: bool = False        # If True, use 80%->20% time-scaled stop
    scaled_in: bool = False               # True if we've already scaled in (once per position)
    extreme_low_scaled: bool = False    # True if we've already scaled in at low extreme zone (<=$0.40)
    extreme_high_scaled: bool = False   # True if we've already scaled in at high extreme zone ($0.60-$0.80)
    extreme_very_high_scaled: bool = False  # True if we've scaled in at very high zone ($0.70+ for >95% entry)
    is_candle_duration: bool = False    # True if this is a candle-duration position (no SL/TP)

    def __post_init__(self):
        """Initialize computed fields after dataclass init."""
        if self.avg_price == 0.0:
            self.avg_price = self.entry_price
        if self.peak_price == 0.0:
            self.peak_price = self.entry_price
        if self.entry_confidence == 0:
            self.entry_confidence = self.confidence

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
        Check if we should scale in based on price levels.
        
        Tony's price-level scale-ins:
        - YES: scale in at $0.60, $0.70, $0.80 (when moving up)
        - NO: scale in at $0.40, $0.30, $0.20 (when moving down)
        
        Conditions:
        - Position must be profitable (market moving in our direction)
        - Price must have moved $0.10+ in our favor from entry
        - Max 3 contracts per side total
        - Scale in once per price level crossing
        """
        # Check max contracts cap (3 per side)
        if self.size >= 3.0:
            return False
        
        # Check if position is profitable (market moving in our direction)
        if self.side == "yes":
            profit_pct = (current_price - self.entry_price) / self.entry_price if self.entry_price > 0 else 0
            if profit_pct <= 0:
                return False  # Not profitable, don't scale in
            # Scale in at price levels: $0.60, $0.70, $0.80
            if current_price >= 0.60 and not self.extreme_high_scaled:
                return True
            if current_price >= 0.70 and self.extreme_high_scaled and not self.extreme_very_high_scaled:
                return True
            if current_price >= 0.80 and self.extreme_very_high_scaled and not self.extreme_high_scaled:
                return True  # Third level
        else:  # no side
            profit_pct = (self.entry_price - current_price) / self.entry_price if self.entry_price > 0 else 0
            if profit_pct <= 0:
                return False  # Not profitable, don't scale in
            # Scale in at price levels: $0.40, $0.30, $0.20
            if current_price <= 0.40 and not self.extreme_low_scaled:
                return True
            if current_price <= 0.30 and self.extreme_low_scaled and not self.extreme_high_scaled:
                return True
            if current_price <= 0.20 and self.extreme_high_scaled:
                return True  # Third level
        
        return False

    def get_scale_in_size(self) -> float:
        """
        Return the scale-in size: 50% of Kelly-derived initial size, minimum 1 contract.
        """
        # Scale in with 1 contract (or 50% of initial Kelly size, min 1)
        return max(1.0, self.size * 0.5)

    def record_scale_in(self, new_price: float, additional_size: float):
        """Record a scale-in: update average price, size, and set scaled_in flag."""
        total_cost = (self.size * self.avg_price) + (additional_size * new_price)
        self.size += additional_size
        self.avg_price = total_cost / self.size
        self.scale_in_count += 1
        self.scaled_in = True  # Mark as scaled in (only scale once per position)
        logger.info(f"{self.ticker}: SCALED IN @ ${new_price:.4f} (+{additional_size:.1f} contracts), new_size={self.size:.1f}, avg_price=${self.avg_price:.4f}, CONF={self.confidence}")

    def should_extreme_scale_in(self, current_price: float) -> tuple:
        """
        Check if we should scale in at extreme price zones.
        
        Returns: (should_scale: bool, zone: str) where zone is 'low', 'high', or ''
        
        High zones (when winning) - based on ENTRY confidence tiers:
        - >95% entry: scale in at $0.60 (high), $0.70 (very_high)
        - 90-95% entry: scale in at $0.70 (high)
        - 85-90% entry: scale in at $0.80 (high)
        
        Low extreme (when winning) - for BUY NO direction:
        - 60%+ entry confidence: scale in when price <= $0.40
        
        Rules:
        - Position must be profitable (market moving in our direction)
        - Max 3 contracts per side total
        - Only scale in once per zone (extreme_low_scaled / extreme_high_scaled flags)
        """
        # Check max contracts per side (max 3 total)
        if self.size >= 3.0:
            return False, ""
        
        # Check if position is profitable (market moving in our direction)
        if self.side == "yes":
            profit_pct = (current_price - self.entry_price) / self.entry_price if self.entry_price > 0 else 0
            if profit_pct <= 0:
                return False, ""  # Not profitable, don't scale in
        else:
            profit_pct = (self.entry_price - current_price) / self.entry_price if self.entry_price > 0 else 0
            if profit_pct <= 0:
                return False, ""  # Not profitable, don't scale in
        
        # Low extreme zone: price <= $0.40 (60%+ entry confidence, for BUY NO)
        if current_price <= 0.40 and self.entry_confidence >= 60 and not self.extreme_low_scaled:
            return True, "low"
        
        # High extreme zones by ENTRY confidence (when winning)
        entry_conf = self.entry_confidence
        if entry_conf > 95:
            # >95%: scale in at $0.60 (high), then $0.70 (very_high)
            if current_price >= 0.60 and not self.extreme_high_scaled:
                return True, "high"
            elif current_price >= 0.70 and self.extreme_high_scaled and not self.extreme_very_high_scaled:
                return True, "very_high"
        elif entry_conf >= 90:
            # 90-95%: scale in at $0.70 (high)
            if current_price >= 0.70 and not self.extreme_high_scaled:
                return True, "high"
        elif entry_conf >= 85:
            # 85-90%: scale in at $0.80 (high)
            if current_price >= 0.80 and not self.extreme_high_scaled:
                return True, "high"
        elif entry_conf >= 60:
            # 60-84%: scale in at $0.60 (high) - legacy low-confidence extreme
            if current_price >= 0.60 and not self.extreme_high_scaled:
                return True, "high"
        
        return False, ""

    def record_extreme_scale_in(self, zone: str, new_price: float):
        """Record an extreme zone scale-in: update average price, size, and set zone flag."""
        additional_size = 1.0  # Scale in +1 contract for extreme zones
        total_cost = (self.size * self.avg_price) + (additional_size * new_price)
        self.size += additional_size
        self.avg_price = total_cost / self.size
        self.scale_in_count += 1
        if zone == "very_high":
            self.extreme_very_high_scaled = True
        elif zone.startswith("high"):
            self.extreme_high_scaled = True
        elif zone == "low":
            self.extreme_low_scaled = True
        logger.info(f"{self.ticker}: EXTREME ZONE SCALED IN ({zone.upper()}) @ ${new_price:.4f} (+{additional_size:.1f} contracts), new_size={self.size:.1f}, avg_price=${self.avg_price:.4f}")


class StrategyEngine:
    """Evaluates markets and generates trading signals."""

    GRACE_PERIOD_SEC = 120          # Never enter in first 2 minutes of a series

    def __init__(self, cash_available: float, api=None):
        self.cash = cash_available
        self.api = api  # Optional KalshiAPI for First Cross floor_strike fetching
        self.tracker = StrategyTracker(KELLY_TRACKED_TRADES)
        self.first_cross = FirstCrossTracker()  # YES price midpoint crossing (existing)
        self.coin_first_cross = FirstCrossCoinTracker()  # Coin price vs target crossing (new)
        self.momentum = MomentumTracker()  # Momentum tracker - fires on midpoint cross
        self.candle_duration = CandleDurationTracker()  # Nerd's candle time-above-open tracker
        self._floor_strikes: Dict[str, float] = {}  # Cache floor_strike per ticker
        self._market_open_times: Dict[str, float] = {}  # Track when each market opened (for grace period)

    def reset_cross_tracker(self, ticker: str):
        """Reset the first cross tracker for a ticker (when market expires/closes)."""
        self.first_cross.reset(ticker)
        self.candle_duration.reset(ticker)
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

    def calculate_kelly_size(self, strategy: Strategy, prob: float, confidence: int = 50, entry_price: float = 0.50, cash_override: float = None) -> Tuple[float, float, int]:
        """
        Calculate Kelly Criterion bet size using historical strategy performance,
        then apply 50% Kelly for entry + confidence tier sizing.

        Returns (contracts, kelly_pct, confidence) tuple.
        - contracts: number of contracts to buy (whole, capped at 3)
        - kelly_pct: the Kelly % used (for logging)
        - confidence: the confidence score (0-100)

        Tony's Kelly Compounding with Confidence Tiers:
        - CONF 80-89: +2 contracts (base 1 + 2 = 3 total, or base 2 + 2 = 4 capped at 3)
        - CONF 90+: +2 contracts + 50% size boost
        - CONF <40: Skip (weak signal, don't trade)

        Entry at midpoint ($0.50): start with 50% Kelly sizing (half the recommended size).
        Scale-ins at price levels ($0.60/$0.70/$0.80 for YES, $0.40/$0.30/$0.20 for NO).

        Hard caps: MAX_BET = $2, MIN_BET = $0.10, MAX 3 contracts per side.
        """
        import math

        # Skip if confidence too low (CONF=40 or below is skipped)
        if confidence <= 40:
            return 0.0, 0.0, confidence

        if prob <= 0 or prob >= 1:
            return 0.0, 0.0, confidence

        # Get Kelly % from historical performance
        kelly_pct = self.tracker.get_kelly_pct(strategy)

        # CONFIDENCE MULTIPLIER (Tony's update)
        # CONF 90+: Kelly * 1.5 (boosted)
        # CONF 80-89: Kelly * 1.0 (full)
        # CONF 60-79: Kelly * 0.75 (reduced)
        # CONF 40-59: Kelly * 0.50 (moderate)
        if confidence >= 90:
            conf_mult = 1.5
        elif confidence >= 80:
            conf_mult = 1.0
        elif confidence >= 60:
            conf_mult = 0.75
        else:
            conf_mult = 0.50

        # Tony's 50% Kelly at entry (half the recommended size)
        # 50% Kelly = half the calculated Kelly for compounding
        entry_kelly_pct = kelly_pct * 0.5
        
        # Effective Kelly = entry_kelly_pct * confidence_multiplier
        effective_pct = entry_kelly_pct * conf_mult

        # Convert to dollar amount to risk
        cash_for_kelly = cash_override if cash_override is not None else self.cash
        dollar_amount = cash_for_kelly * effective_pct

        # Clamp dollar amount to hard limits
        dollar_amount = max(MIN_BET, min(MAX_BET, dollar_amount))

        # Convert dollar amount to contracts
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

        # CONFIDENCE TIER SIZING: Add contracts based on confidence
        # CONF 80-89: +2 contracts (base + 2)
        # CONF 90+: +2 contracts + 50% boost
        if confidence >= 90:
            contracts = contracts + 2  # +2 contracts
            contracts = int(contracts * 1.5)  # 50% boost
        elif confidence >= 80:
            contracts = contracts + 2  # +2 contracts

        # Cap at MAX 3 contracts per side (Tony's max)
        contracts = min(contracts, 3)

        # Ensure minimum 1 contract
        contracts = max(1, contracts)

        # Log the Kelly sizing result for debugging
        logger.info(f"KELLY CALCULATED: strategy={strategy.value} | CONF={confidence} | kelly_pct={kelly_pct:.2%} | conf_mult={conf_mult:.2f}x | effective_pct={effective_pct:.2%} | dollar_amount=${dollar_amount:.2f} | entry_price=${entry_price:.4f} | contracts={int(contracts):d}")

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

    def evaluate_market(self, market: Market, coin: str = None, price_vs_strike_pct: float = 0.0, ob_imbalance: float = 0.0) -> List[TradeSignal]:
        """
        NEW SERIES STRATEGY - Grace Period Only:

        1. GRACE PERIOD: Never enter in first 2 minutes of a new series
        2. ONLY FIRST_CROSS and MOMENTUM signals
        3. ALL entry conditions must be met:
           - Price between $0.20-$0.80
           - At least 2 minutes into the series
           - Has actual Coinbase momentum (not neutral)
           - For MOMENTUM: price at extreme ($0.10 or $0.90) AND clear Coinbase bias

        TIER 1 FEATURES:
        - price_vs_strike_pct: Coinbase price deviation from floor_strike in %
          If > 0 (above strike) → YES bias, If < 0 (below strike) → NO bias
        - ob_imbalance: Orderbook imbalance (-1 to +1)
          Heavy YES imbalance (>0.3) + our signal = stronger YES entry
          Heavy NO imbalance (<-0.3) + our signal = stronger NO entry
        
        TIER 1: Entry Blackout 10-11 minute window
        - Skip ALL signals when time_remaining is between 300-360 seconds (10-11 min into candle)
        - Based on competitor data showing this window has poor win rates

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
            return []

        # === ENTRY PRICE GUARD: Block entries below $0.35 (0% win rate zone) ===
        # Nerd's backtest: entry price <$0.35 has 0% win rate, 100% cut-loss rate
        if mid_price < 0.35:
            logger.info(f"{market.ticker}: ENTRY SKIP: entry price ${mid_price:.4f} < $0.35 (0% win zone)")
            return []

        # === TIER 1: ENTRY BLACKOUT 10-11 MINUTE WINDOW ===
        # Skip ALL signals when time_remaining is between 300-360 seconds (10-11 min into candle)
        # Based on competitor data showing this window has poor win rates
        if 300 <= time_left <= 360:
            logger.debug(f"{market.ticker}: TIER 1 BLACKOUT - in 10-11 min window (time_left={time_left}s) - SKIPPING")
            return []

        # === TIER 1: Log price_vs_strike_pct and ob_imbalance for context ===
        if abs(price_vs_strike_pct) > 0.05:
            bias = "YES" if price_vs_strike_pct > 0 else "NO"
            logger.debug(f"{market.ticker}: TIER 1 price_vs_strike={price_vs_strike_pct:.3f}% ({bias} bias)")
        if abs(ob_imbalance) > 0.15:
            bias = "YES" if ob_imbalance > 0 else "NO"
            logger.debug(f"{market.ticker}: TIER 1 ob_imbalance={ob_imbalance:.3f} ({bias} heavy)")

        # === TRACK MARKET OPEN TIME for grace period ===
        if market.ticker not in self._market_open_times:
            self._market_open_times[market.ticker] = time.time()

        market_age_sec = time.time() - self._market_open_times.get(market.ticker, time.time())

        # === GRACE PERIOD: Only applies to MOMENTUM, not FIRST_CROSS ===
        # (Track market age for MOMENTUM check below)

        # === DEEP BUY: DISABLED - Only candle-duration signals ===
        # deep_buy_signal = self._check_deep_buy(market, mid_price, time_left)
        # if deep_buy_signal:
        #     return [deep_buy_signal]

        # === MOMENTUM: DISABLED - Only candle-duration signals ===
        # momentum_signal = self.momentum.update(market.ticker, mid_price)
        # if momentum_signal:
        #     ... (momentum disabled)

        # === CANDLE DURATION: Nerd's time-above-open signal (FIXED 2026-04-10) ===
        # FIRE ONLY at candle close (when new candle starts), based on COMPLETED candle's stats
        # BUY YES when >90% above previous close for full candle AND entry price <= $0.85
        # BUY NO when <40% above previous close
        # ONLY for ETH and SOL (98.8% and 98.7% win rates)
        # NO SL/TP for candle-duration positions (hold to expiry)
        candle_signal = self.candle_duration.update(market.ticker, mid_price, coin)
        if candle_signal:
            # === TIER 1: Integrate price_vs_strike_pct and ob_imbalance signals ===
            # Adjust confidence based on Tier 1 signals
            adj_confidence = candle_signal.confidence
            tier1_boost = 0
            tier1_conflict = False
            
            # Check price_vs_strike alignment
            if price_vs_strike_pct > 0.05:  # Above strike → YES bias
                if candle_signal.side == 'yes':
                    tier1_boost += 5
                    logger.debug(f"{market.ticker}: TIER 1 price_vs_strike YES alignment +5 boost")
                else:
                    tier1_conflict = True
                    logger.debug(f"{market.ticker}: TIER 1 price_vs_strike conflict (coin above strike but signal is NO)")
            elif price_vs_strike_pct < -0.05:  # Below strike → NO bias
                if candle_signal.side == 'no':
                    tier1_boost += 5
                    logger.debug(f"{market.ticker}: TIER 1 price_vs_strike NO alignment +5 boost")
                else:
                    tier1_conflict = True
                    logger.debug(f"{market.ticker}: TIER 1 price_vs_strike conflict (coin below strike but signal is YES)")
            
            # Check ob_imbalance alignment
            if ob_imbalance > 0.3:  # Heavy YES imbalance
                if candle_signal.side == 'yes':
                    tier1_boost += 5
                    logger.debug(f"{market.ticker}: TIER 1 ob_imbalance YES alignment +5 boost")
                else:
                    tier1_conflict = True
                    logger.debug(f"{market.ticker}: TIER 1 ob_imbalance conflict (heavy YES imbalance but signal is NO)")
            elif ob_imbalance < -0.3:  # Heavy NO imbalance
                if candle_signal.side == 'no':
                    tier1_boost += 5
                    logger.debug(f"{market.ticker}: TIER 1 ob_imbalance NO alignment +5 boost")
                else:
                    tier1_conflict = True
                    logger.debug(f"{market.ticker}: TIER 1 ob_imbalance conflict (heavy NO imbalance but signal is YES)")
            
            # === SWEET SPOT ENTRY ZONE BOOST: +3 conf for $0.45-$0.50 entries ===
            # Nerd's backtest: entry zone $0.45-$0.50 has 75% win rate (best zone)
            if 0.45 <= mid_price <= 0.50:
                tier1_boost += 3
                logger.debug(f"{market.ticker}: SWEET SPOT ENTRY +3 boost (${mid_price:.4f} in $0.45-$0.50 zone)")
            
            # If there's a conflict, reduce confidence significantly or skip
            if tier1_conflict:
                adj_confidence = max(40, candle_signal.confidence - 15)  # At least reduce to skip threshold
                logger.info(f"{market.ticker}: TIER 1 CONFLICT detected - reduced confidence to {adj_confidence}")
            else:
                adj_confidence = candle_signal.confidence + tier1_boost
            
            # Skip if confidence drops below threshold after adjustment
            if adj_confidence < 50:
                logger.info(f"{market.ticker}: TIER 1 signal filtered - adjusted confidence {adj_confidence} below threshold")
                return []
            
            # Calculate Kelly size based on adjusted probability and confidence
            prob = mid_price if candle_signal.side == 'yes' else (1 - mid_price)
            size, kelly_pct, confidence = self.calculate_kelly_size(
                Strategy.MOMENTUM, prob, adj_confidence, mid_price
            )
            
            # Calculate scale-in size (50% of Kelly size, min 1)
            scale_in_size = max(1, int(size * 0.5))
            
            above_pct = self.candle_duration.get_above_pct(market.ticker)
            
            # Log with Tier 1 context
            logger.info(
                f"CANDLE_DURATION SIGNAL: {market.ticker} ({coin}) | "
                f"Side: {candle_signal.side} @ ${mid_price:.4f} | "
                f"Above open: {above_pct:.1%} | "
                f"contracts={int(size):d} | scale_in={int(scale_in_size):d} | "
                f"CONF={adj_confidence} (base={candle_signal.confidence}, tier1_boost={tier1_boost}) | "
                f"price_vs_strike={price_vs_strike_pct:.3f}% | ob_imbalance={ob_imbalance:.3f} | "
                f"NO SL/TP (hold to expiry)"
            )
            
            candle_signal.size = int(size)
            candle_signal.scale_in_size = int(scale_in_size)
            candle_signal.confidence = adj_confidence
            return [candle_signal]

        # === Get Coinbase bias - DISABLED (only candle-duration) ===
        bias = 'neutral'  # get_coinbase_bias(coin)

        # === MOMENTUM (Coinbase bias): DISABLED - Only candle-duration signals ===
        # All Coinbase bias momentum disabled - only candle-duration strategy active
        # if is_momentum_enabled() and bias != 'neutral' and (mid_price >= 0.20 and mid_price <= 0.80):
        #     ... (momentum with Coinbase bias - disabled)

        # === FIRST CROSS: DISABLED - MomentumTracker is now PRIMARY only ===
        # --- First Cross: Coin price vs target price ---
        # DISABLED by Pixel 2026-04-10 - MOMENTUM is the only primary strategy
        # if market.ticker not in self._floor_strikes:
        #     if self.api is not None:
        #         floor_strike = self.coin_first_cross.get_floor_strike(market.ticker, self.api)
        #         if floor_strike is not None:
        #             self._floor_strikes[market.ticker] = floor_strike
        #             logger.info(f"FIRST_CROSS: {market.ticker} target price set to ${floor_strike:,.2f}")

        has_coin_cross = False
        # if market.ticker in self._floor_strikes and coin:
        #     target_price = self._floor_strikes[market.ticker]
        #     cross_direction = self.coin_first_cross.check_cross(market.ticker, coin, target_price, self.api)
        #
        #     if cross_direction:
        #         has_coin_cross = True
        #         ... (rest of coin first cross logic - DISABLED)

        # --- First Cross: Midpoint crossing ---
        has_midpoint_cross = False  # DISABLED - using MomentumTracker instead
        # has_midpoint_cross = self.first_cross.has_crossed(market.ticker)
        # if not has_coin_cross:
        #     cross_event = self.first_cross.update(market.ticker, mid_price)
        #     if cross_event:
        #         has_midpoint_cross = True

        # FIRST_CROSS fully disabled - MomentumTracker handles all midpoint crossings
        if False and not is_first_cross_enabled():
            pass  # first_cross disabled (off-hours, momentum running)
        elif False and self.first_cross.should_wait(market.ticker, mid_price):
            logger.debug(f"FIRST_CROSS: {market.ticker} in dead zone (${mid_price:.4f}) - WAITING")
        elif False and (has_midpoint_cross or (has_coin_cross == False and self.first_cross.get_preferred_side(market.ticker))):
            # All FIRST_CROSS logic disabled - using MomentumTracker instead
            pass

        # === MOMENTUM_FORCE: DISABLED - Only candle-duration signals ===
        # no_cross_yet = not has_coin_cross and not has_midpoint_cross
        # if is_momentum_enabled() and no_cross_yet and market_age_sec >= 60 and bias != 'neutral' and (mid_price < 0.10 or mid_price > 0.90):
        #     ... (momentum_force - disabled)

        return []

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
            direction='buy',
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
            # Use INITIAL_STOP_PCT (which is 0.0 = disabled per Tony's request)
            stop_pct = INITIAL_STOP_PCT

        # === NEAR-EXPIRY EXIT (last 60 seconds) ===
        if time_left <= 60:
            logger.info(f"{position.ticker}: Near expiry ({time_left}s) - closing position")
            return True, f"Expiry: closing at ${current_price:.4f}"

        # === TONY'S TWO-STAGE STOP SYSTEM ===

        if position.side == "yes":
            # YES: We profit when price goes UP

            # Stage 1: STATIC STOP (skip if stop_pct disabled)
            if stop_pct > 0:
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

            # Stage 1: STATIC STOP (skip if stop_pct disabled)
            if stop_pct > 0:
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
