# strategies.py - Superbot Trading Strategies

import logging
import os
import subprocess
import json
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, List
from collections import deque
from enum import Enum

from config import (
    MAX_BET, MIN_BET, KELLY_FRACTION, MIN_KELLY_BET, MAX_KELLY_BET,
    DEEP_SHORT_ENABLED, DEEP_SHORT_MAX_PRICE, DEEP_MIN_TIME_LEFT_SEC,
    DRIFT_BUY_MIN_PRICE, DRIFT_BUY_MAX_PRICE, DRIFT_MIN_TIME_LEFT_SEC,
    DRIFT_SHORT_MIN_PRICE, DRIFT_SHORT_MAX_PRICE, DRIFT_SHORT_SL_PRICE,
    DRIFT_TP_PCT, DRIFT_SL_PCT, KELLY_TRACKED_TRADES, KELLY_MAX_CAP,
    DRIFT_TP_PRICE,  # New: absolute TP price threshold
    DEAD_ZONE_MIN, DEAD_ZONE_MAX,  # Dead zone - no trade
    DRIFT_BUY_STOP_LOSS, DRIFT_SHORT_STOP_LOSS,  # Absolute stop loss prices
    AI_EDGE_THRESHOLD,  # Minimum edge required (5%)
    AI_PROBABILITY_ENABLED  # Enable AI probability estimation
)
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
    DEEP_SHORT = "deep_short"  # Changed: was DEEP_BUY (buying tails is wrong direction)
    DRIFT_BUY = "drift_buy"
    DRIFT_SHORT = "drift_short"
    FIRST_CROSS = "first_cross"  # Tony's insight: first direction of breakout tends to hold
    NONE = "none"


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
            Strategy.DRIFT_BUY: deque(maxlen=tracked_trades),
            Strategy.DRIFT_SHORT: deque(maxlen=tracked_trades),
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
        
        if R <= 0:
            return 0.0
        
        # Kelly formula: Kelly % = (W * (R+1) - 1) / R
        kelly_pct = (W * (R + 1) - 1) / R
        
        # Cap at maximum (never bet more than 50% of balance)
        kelly_pct = min(kelly_pct, KELLY_MAX_CAP)
        
        # Don't bet if Kelly is negative or zero
        if kelly_pct <= 0:
            return 0.0
        
        return kelly_pct


@dataclass
class TradeSignal:
    """Represents a trading signal."""
    strategy: Strategy
    ticker: str
    side: str  # 'yes' or 'no'
    price: float  # Entry price
    size: float  # Bet size in dollars
    reason: str  # Human readable reason
    take_profit: Optional[float] = None  # For DRIFT strategies
    stop_loss: Optional[float] = None    # For DRIFT strategies
    tp_pct: Optional[float] = None       # TP percentage
    sl_pct: Optional[float] = None        # SL percentage


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
    
    def current_value(self, current_price: float) -> float:
        """Calculate current value of position."""
        if self.side == "yes":
            # Value = size * (current_price - entry_price) + size
            # When YES goes to $1, we win size; at $0, we lose size
            return self.size * current_price
        else:
            # Value = size * ((1 - current_price) - (1 - entry_price)) + size
            return self.size * (1 - current_price)


class StrategyEngine:
    """Evaluates markets and generates trading signals."""
    
    def __init__(self, cash_available: float):
        self.cash = cash_available
        self.tracker = StrategyTracker(KELLY_TRACKED_TRADES)
        self.first_cross = FirstCrossTracker()  # Tony's first crossing insight
    
    def reset_cross_tracker(self, ticker: str):
        """Reset the first cross tracker for a ticker (when market expires/closes)."""
        self.first_cross.reset(ticker)
    
    def update_cash(self, cash: float):
        """Update available cash for Kelly sizing."""
        self.cash = cash
    
    def record_trade_result(self, strategy: Strategy, pnl: float):
        """Record a trade result for Kelly tracking."""
        self.tracker.record_trade(strategy, pnl)
        W, R = self.tracker.get_stats(strategy)
        kelly_pct = self.tracker.get_kelly_pct(strategy)
        logger.info(f"Strategy {strategy.value} stats: W={W:.2%}, R={R:.2f}x, Kelly={kelly_pct:.2%}")
    
    def calculate_kelly_size(self, strategy: Strategy, prob: float) -> Tuple[float, float]:
        """
        Calculate Kelly Criterion bet size using historical strategy performance.
        
        Returns (bet_size, kelly_pct) tuple.
        - bet_size: dollar amount to bet (clamped to $2 min/$2 max)
        - kelly_pct: the Kelly % used (for logging)
        """
        if prob <= 0 or prob >= 1:
            return MIN_BET, 0.0
        
        # Get Kelly % from historical performance
        kelly_pct = self.tracker.get_kelly_pct(strategy)
        
        # Apply Kelly fraction for additional safety
        kelly_pct = kelly_pct * KELLY_FRACTION
        
        # Convert to dollar amount
        bet = self.cash * kelly_pct
        
        # Clamp to hard limits ($2 min, $2 max)
        bet = max(MIN_KELLY_BET, min(MAX_KELLY_BET, bet))
        
        return bet, kelly_pct
    
    def evaluate_market(self, market: Market) -> Optional[TradeSignal]:
        """Evaluate a market and return a trading signal if conditions are met."""
        
        # Use mid price for decision
        mid_price = (market.yes_bid + market.yes_ask) / 2
        time_left = market.time_to_expiry_sec()
        
        logger.debug(f"Evaluating {market.ticker}: price=${mid_price:.4f}, time_left={time_left}s")
        
        # FIRST CROSS TRACKING: Update crossing state
        cross_event = self.first_cross.update(market.ticker, mid_price)
        
        # FIRST CROSS INSIGHT: If price is in dead zone and hasn't crossed, WAIT
        if self.first_cross.should_wait(market.ticker, mid_price):
            logger.debug(f"FIRST_CROSS: {market.ticker} in dead zone (${mid_price:.4f}) and hasn't crossed yet - WAITING")
            return None
        
        # Get preferred side based on first cross (for biasing entries)
        preferred_side = self.first_cross.get_preferred_side(market.ticker)
        if preferred_side:
            logger.debug(f"FIRST_CROSS: {market.ticker} has crossed {preferred_side} first - biasing entries")
        
        # AI Probability Estimation: Check if we have genuine edge
        if AI_PROBABILITY_ENABLED:
            ai_prob = self._estimate_ai_probability(market, mid_price)
            if ai_prob is not None:
                edge = abs(ai_prob - mid_price)
                if edge < AI_EDGE_THRESHOLD:
                    logger.debug(f"AI: {market.ticker} - No edge (market={mid_price:.4f}, AI={ai_prob:.4f}, edge={edge:.4f} < {AI_EDGE_THRESHOLD})")
                    return None
                logger.info(f"AI: {market.ticker} - Edge found! market={mid_price:.4f}, AI={ai_prob:.4f}, edge={edge:.4f}")
        
        # Check DEEP SHORT first (highest priority) - fading the longshot
        signal = self._check_deep_short(market, mid_price, time_left)
        if signal:
            return signal
        
        # Check DRIFT BUY
        signal = self._check_drift_buy(market, mid_price, time_left)
        if signal:
            return signal
        
        # Check DRIFT SHORT
        signal = self._check_drift_short(market, mid_price, time_left)
        if signal:
            return signal
        
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
        size, kelly_pct = self.calculate_kelly_size(Strategy.DEEP_SHORT, prob)
        
        logger.info(f"DEEP SHORT signal: {market.ticker} @ ${mid_price:.4f}, size=${size:.2f}, Kelly={kelly_pct:.2%}, time_left={time_left}s")
        
        return TradeSignal(
            strategy=Strategy.DEEP_SHORT,
            ticker=market.ticker,
            side="no",  # We SELL YES (buy NO)
            price=mid_price,
            size=size,
            reason=f"DEEP SHORT: Selling YES at ${mid_price:.4f} (< ${DEEP_SHORT_MAX_PRICE}), fading the longshot",
            take_profit=None,  # No TP - ride to expiry
            stop_loss=None     # No SL - ride to expiry
        )
    
    def _check_drift_buy(self, market: Market, mid_price: float, time_left: int) -> Optional[TradeSignal]:
        """
        DRIFT BUY: YES $0.30-$0.38 → mean reversion, TP at $0.90+, SL at $0.22
        
        TP: lock in near-wins when price reaches $0.90
        SL: absolute $0.22 (Nerd's research - not percentage)
        Dead zone: no trades $0.45-$0.55
        
        FIRST CROSS INSIGHT: If crossed DOWN first (price went from above $0.50 to below),
        drift_buy is weaker because momentum is downward. Skip if first cross was down.
        Only take drift_buy if first cross was UP or hasn't crossed yet (below midline).
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
        # Bias just modifies our confidence, doesn't block entries
        coin = market.ticker.replace('KX', '').replace('15M', '')
        bias = get_coinbase_bias(coin)
        if bias == 'bearish':
            # Mild bullish bias check - allow drift_buy even with neutral/bearish bias
            # since we need to trade to make $200
            logger.debug(f"DRIFT BUY: {market.ticker} - Coinbase bias={bias}, using as signal boost only")
        
        # Calculate size using Kelly with historical strategy performance
        prob = mid_price
        size, kelly_pct = self.calculate_kelly_size(Strategy.DRIFT_BUY, prob)
        
        # Calculate TP and SL prices
        # TP: Lock in profit when YES reaches $0.90+ (near maximum)
        tp_price = DRIFT_TP_PRICE  # $0.90 absolute threshold
        # SL: Absolute $0.22 stop loss (Nerd's research)
        sl_price = DRIFT_BUY_STOP_LOSS  # $0.22 absolute
        
        logger.info(f"DRIFT BUY signal: {market.ticker} @ ${mid_price:.4f}, size=${size:.2f}, Kelly={kelly_pct:.2%}, TP=${tp_price:.4f}, SL=${sl_price:.4f}, Coinbase={bias}, first_cross={preferred_side or 'none'}")
        
        return TradeSignal(
            strategy=Strategy.DRIFT_BUY,
            ticker=market.ticker,
            side="yes", 
            price=mid_price,
            size=size,
            reason=f"DRIFT BUY: YES at ${mid_price:.4f} (mean reversion), TP ${tp_price:.2f}, SL ${sl_price:.2f}, Coinbase={bias}, first_cross={preferred_side}",
            take_profit=tp_price,
            stop_loss=sl_price,
            tp_pct=DRIFT_TP_PCT,
            sl_pct=DRIFT_SL_PCT
        )
    
    def _check_drift_short(self, market: Market, mid_price: float, time_left: int) -> Optional[TradeSignal]:
        """
        DRIFT SHORT: YES $0.55-$0.62 → sell overpriced, TP 20%, SL at $0.75
        This means we're SELLING YES (betting it will go down)
        
        SL: absolute $0.75 stop loss (Nerd's research - not percentage)
        Dead zone: no trades $0.45-$0.55
        
        FIRST CROSS INSIGHT: If crossed UP first (price went from below $0.50 to above),
        drift_short is weaker because momentum is upward. Skip if first cross was up.
        Only take drift_short if first cross was DOWN or hasn't crossed yet (above midline).
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
        # We sell YES at current price, expecting it to drop
        prob = 1 - mid_price  # Probability that YES loses
        size, kelly_pct = self.calculate_kelly_size(Strategy.DRIFT_SHORT, prob)
        
        # Calculate TP and SL for short position
        # TP: YES drops, we profit. TP means price drops by 20%
        tp_price = mid_price * (1 - DRIFT_TP_PCT)
        # SL: Absolute $0.75 stop loss (Nerd's research)
        sl_price = DRIFT_SHORT_STOP_LOSS  # $0.75 absolute
        
        logger.info(f"DRIFT SHORT signal: {market.ticker} @ ${mid_price:.4f}, size=${size:.2f}, Kelly={kelly_pct:.2%}, TP=${tp_price:.4f}, SL=${sl_price:.4f}, first_cross={preferred_side or 'none'}")
        
        return TradeSignal(
            strategy=Strategy.DRIFT_SHORT,
            ticker=market.ticker,
            side="no",  # We SELL YES (buy NO)
            price=mid_price,
            size=size,
            reason=f"DRIFT SHORT: Selling YES at ${mid_price:.4f} (overpriced), TP ${tp_price:.4f}, SL ${sl_price:.4f}",
            take_profit=tp_price,
            stop_loss=sl_price,
            tp_pct=DRIFT_TP_PCT,
            sl_pct=DRIFT_SL_PCT
        )
    
    def check_position_exit(self, position: Position, current_price: float) -> Tuple[bool, str]:
        """
        Check if a position should be exited.
        Returns (should_exit, reason).
        """
        if position.strategy == Strategy.DEEP_SHORT:
            # No exit for DEEP SHORT - ride to expiry (we're fading the longshot)
            return False, ""
        
        if position.take_profit is not None:
            # Check TP
            if position.side == "yes" and current_price >= position.take_profit:
                return True, f"TP hit: ${current_price:.4f} >= ${position.take_profit:.4f}"
            if position.side == "no" and current_price <= position.take_profit:
                return True, f"TP hit: ${current_price:.4f} <= ${position.take_profit:.4f}"
        
        if position.stop_loss is not None:
            # Check SL
            if position.side == "yes" and current_price <= position.stop_loss:
                return True, f"SL hit: ${current_price:.4f} <= ${position.stop_loss:.4f}"
            if position.side == "no" and current_price >= position.stop_loss:
                return True, f"SL hit: ${current_price:.4f} >= ${position.stop_loss:.4f}"
        
        return False, ""
