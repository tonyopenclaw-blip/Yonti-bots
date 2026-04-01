# strategies.py - Superbot Trading Strategies

import logging
from dataclasses import dataclass
from typing import Optional, Tuple
from enum import Enum

from config import (
    MAX_BET, MIN_BET, KELLY_FRACTION, MIN_KELLY_BET, MAX_KELLY_BET,
    DEEP_BUY_MAX_PRICE, DEEP_MIN_TIME_LEFT_SEC,
    DRIFT_BUY_MIN_PRICE, DRIFT_BUY_MAX_PRICE, DRIFT_MIN_TIME_LEFT_SEC,
    DRIFT_SHORT_MIN_PRICE, DRIFT_SHORT_MAX_PRICE,
    DRIFT_TP_PCT, DRIFT_SL_PCT
)
from kalshi_api import Market

logger = logging.getLogger(__name__)


class Strategy(Enum):
    DEEP_BUY = "deep_buy"
    DRIFT_BUY = "drift_buy"
    DRIFT_SHORT = "drift_short"
    NONE = "none"


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
    
    def update_cash(self, cash: float):
        """Update available cash for Kelly sizing."""
        self.cash = cash
    
    def calculate_kelly_size(self, edge: float, prob: float) -> float:
        """
        Calculate Kelly Criterion bet size.
        edge = expected_return - 1
        prob = probability of winning
        Uses fraction of Kelly for safety.
        """
        if prob <= 0 or prob >= 1:
            return 0
        
        # Kelly formula: f* = (bp - q) / b
        # where b = net odds, p = prob of win, q = prob of loss
        b = 1 / prob - 1  # Net odds
        q = 1 - prob
        kelly = (b * prob - q) / b
        
        if kelly <= 0:
            return 0
        
        # Apply Kelly fraction for safety
        kelly = kelly * KELLY_FRACTION
        
        # Convert to dollar amount
        bet = self.cash * kelly
        
        # Clamp to limits
        return max(MIN_KELLY_BET, min(MAX_KELLY_BET, bet))
    
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
        
        # Calculate size - use Kelly but cap at max_bet
        prob = mid_price  # YES price ≈ probability
        edge = 1 / prob - 1 if prob > 0 else 0
        size = min(MAX_BET, max(MIN_BET, self.cash * KELLY_FRACTION * edge))
        size = max(MIN_BET, min(MAX_BET, size))
        
        logger.info(f"DEEP BUY signal: {market.ticker} @ ${mid_price:.4f}, size=${size:.2f}, time_left={time_left}s")
        
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
        
        # Calculate Kelly size
        prob = mid_price
        size = self.calculate_kelly_size(edge=1/prob - 1 if prob > 0 else 0, prob=prob)
        
        # Calculate TP and SL prices
        # TP: +25% from entry (on the $1 payoff scale)
        # If we buy at $0.40, we risk $0.40 to win $0.60
        # TP means YES moves up to ~$0.50 (25% of $1 move)
        tp_price = min(1.0, mid_price * (1 + DRIFT_TP_PCT))
        # SL: -15% loss on our stake
        # SL means YES drops, we lose 15% of our position
        sl_price = mid_price * (1 - DRIFT_SL_PCT)
        
        logger.info(f"DRIFT BUY signal: {market.ticker} @ ${mid_price:.4f}, size=${size:.2f}, TP=${tp_price:.4f}, SL=${sl_price:.4f}")
        
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
        size = self.calculate_kelly_size(edge=1/prob - 1 if prob > 0 else 0, prob=prob)
        
        # Calculate TP and SL for short position
        # TP: YES drops, we profit. TP means price drops by 25%
        tp_price = mid_price * (1 - DRIFT_TP_PCT)
        # SL: YES rises, we lose. SL means price rises by 15%
        sl_price = mid_price * (1 + DRIFT_SL_PCT)
        
        logger.info(f"DRIFT SHORT signal: {market.ticker} @ ${mid_price:.4f}, size=${size:.2f}, TP=${tp_price:.4f}, SL=${sl_price:.4f}")
        
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
