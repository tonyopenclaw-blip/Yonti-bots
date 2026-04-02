# strategies.py - Superbot Trading Strategies

import logging
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, List
from collections import deque
from enum import Enum

from config import (
    MAX_BET, MIN_BET, KELLY_FRACTION, MIN_KELLY_BET, MAX_KELLY_BET,
    DEEP_BUY_MAX_PRICE, DEEP_MIN_TIME_LEFT_SEC,
    DRIFT_BUY_MIN_PRICE, DRIFT_BUY_MAX_PRICE, DRIFT_MIN_TIME_LEFT_SEC,
    DRIFT_SHORT_MIN_PRICE, DRIFT_SHORT_MAX_PRICE,
    DRIFT_TP_PCT, DRIFT_SL_PCT, KELLY_TRACKED_TRADES, KELLY_MAX_CAP
)
from kalshi_api import Market

logger = logging.getLogger(__name__)


class Strategy(Enum):
    DEEP_BUY = "deep_buy"
    DRIFT_BUY = "drift_buy"
    DRIFT_SHORT = "drift_short"
    NONE = "none"


class StrategyTracker:
    """
    Tracks win rate and win/loss ratio per strategy over recent trades.
    Used for Kelly Criterion sizing based on historical strategy performance.
    """
    
    def __init__(self, tracked_trades: int = KELLY_TRACKED_TRADES):
        self.tracked_trades = tracked_trades
        # Store recent trade results per strategy: each entry is (pnl, won)
        self._history: Dict[Strategy, deque] = {
            Strategy.DEEP_BUY: deque(maxlen=tracked_trades),
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
        
        # Check DEEP BUY first (highest priority)
        signal = self._check_deep_buy(market, mid_price, time_left)
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
    
    def _check_deep_buy(self, market: Market, mid_price: float, time_left: int) -> Optional[TradeSignal]:
        """
        DEEP BUY: YES < $0.15 → buy YES, ride to expiry, NO stop loss
        """
        if mid_price >= DEEP_BUY_MAX_PRICE:
            return None
        
        if time_left < DEEP_MIN_TIME_LEFT_SEC:
            logger.debug(f"DEEP BUY: {market.ticker} - not enough time left ({time_left}s)")
            return None
        
        # Calculate size using Kelly with historical strategy performance
        prob = mid_price  # YES price ≈ probability
        size, kelly_pct = self.calculate_kelly_size(Strategy.DEEP_BUY, prob)
        
        logger.info(f"DEEP BUY signal: {market.ticker} @ ${mid_price:.4f}, size=${size:.2f}, Kelly={kelly_pct:.2%}, time_left={time_left}s")
        
        return TradeSignal(
            strategy=Strategy.DEEP_BUY,
            ticker=market.ticker,
            side="yes",
            price=mid_price,
            size=size,
            reason=f"DEEP BUY: YES at ${mid_price:.4f} (< ${DEEP_BUY_MAX_PRICE}), riding to expiry",
            take_profit=None,  # No TP - ride to expiry
            stop_loss=None     # No SL - ride to expiry
        )
    
    def _check_drift_buy(self, market: Market, mid_price: float, time_left: int) -> Optional[TradeSignal]:
        """
        DRIFT BUY: YES $0.35-$0.45 → mean reversion, TP +25%, SL -15%
        """
        if not (DRIFT_BUY_MIN_PRICE <= mid_price <= DRIFT_BUY_MAX_PRICE):
            return None
        
        if time_left < DRIFT_MIN_TIME_LEFT_SEC:
            logger.debug(f"DRIFT BUY: {market.ticker} - not enough time left ({time_left}s)")
            return None
        
        # Calculate size using Kelly with historical strategy performance
        prob = mid_price
        size, kelly_pct = self.calculate_kelly_size(Strategy.DRIFT_BUY, prob)
        
        # Calculate TP and SL prices
        # TP: +25% from entry (on the $1 payoff scale)
        # If we buy at $0.40, we risk $0.40 to win $0.60
        # TP means YES moves up to ~$0.50 (25% of $1 move)
        tp_price = min(1.0, mid_price * (1 + DRIFT_TP_PCT))
        # SL: -15% loss on our stake
        # SL means YES drops, we lose 15% of our position
        sl_price = mid_price * (1 - DRIFT_SL_PCT)
        
        logger.info(f"DRIFT BUY signal: {market.ticker} @ ${mid_price:.4f}, size=${size:.2f}, Kelly={kelly_pct:.2%}, TP=${tp_price:.4f}, SL=${sl_price:.4f}")
        
        return TradeSignal(
            strategy=Strategy.DRIFT_BUY,
            ticker=market.ticker,
            side="yes", 
            price=mid_price,
            size=size,
            reason=f"DRIFT BUY: YES at ${mid_price:.4f} (mean reversion), TP +25%, SL -15%",
            take_profit=tp_price,
            stop_loss=sl_price,
            tp_pct=DRIFT_TP_PCT,
            sl_pct=DRIFT_SL_PCT
        )
    
    def _check_drift_short(self, market: Market, mid_price: float, time_left: int) -> Optional[TradeSignal]:
        """
        DRIFT SHORT: YES $0.55-$0.65 → sell overpriced, TP +25%, SL -15%
        This means we're SELLING YES (betting it will go down)
        """
        if not (DRIFT_SHORT_MIN_PRICE <= mid_price <= DRIFT_SHORT_MAX_PRICE):
            return None
        
        if time_left < DRIFT_MIN_TIME_LEFT_SEC:
            logger.debug(f"DRIFT SHORT: {market.ticker} - not enough time left ({time_left}s)")
            return None
        
        # For short, probability of YES going DOWN is (1 - price)
        # We sell YES at current price, expecting it to drop
        prob = 1 - mid_price  # Probability that YES loses
        size, kelly_pct = self.calculate_kelly_size(Strategy.DRIFT_SHORT, prob)
        
        # Calculate TP and SL for short position
        # TP: YES drops, we profit. TP means price drops by 25%
        tp_price = mid_price * (1 - DRIFT_TP_PCT)
        # SL: YES rises, we lose. SL means price rises by 15%
        sl_price = mid_price * (1 + DRIFT_SL_PCT)
        
        logger.info(f"DRIFT SHORT signal: {market.ticker} @ ${mid_price:.4f}, size=${size:.2f}, Kelly={kelly_pct:.2%}, TP=${tp_price:.4f}, SL=${sl_price:.4f}")
        
        return TradeSignal(
            strategy=Strategy.DRIFT_SHORT,
            ticker=market.ticker,
            side="no",  # We SELL YES (buy NO)
            price=mid_price,
            size=size,
            reason=f"DRIFT SHORT: Selling YES at ${mid_price:.4f} (overpriced), TP +25%, SL -15%",
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
        if position.strategy == Strategy.DEEP_BUY:
            # No exit for DEEP BUY - ride to expiry
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
