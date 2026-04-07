# strategies.py - SuperPolybot Trading Strategies
# Momentum Matrix adapted from Superbot for Polymarket 5-min binaries

import json
import logging
import math
import os
import random
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests

from config import (
    MAX_BET, MIN_BET,
    GRACE_PERIOD_SEC, MIN_TIME_LEFT_SEC,
    MIN_ENTRY_PRICE, MAX_ENTRY_PRICE,
    RSI_OVERSOLD, RSI_OVERBOUGHT, RSI_PERIOD,
    TRAILING_TRIGGER_PCT, TRAILING_BUFFER_PCT,
    MARKET_DURATION_SEC,
    KELLY_MAX_CAP, FIXED_KELLY_PCT,
    COINBASE_API, COINBASE_PRODUCTS,
)

logger = logging.getLogger(__name__)


def get_coinbase_price(coin: str) -> Optional[float]:
    """Fetch current price from Coinbase API."""
    product_id = COINBASE_PRODUCTS.get(coin.upper())
    if not product_id:
        return None
    try:
        url = f"{COINBASE_API}/products/{product_id}/ticker"
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        return float(data.get('price', 0))
    except Exception as e:
        logger.debug(f"Coinbase price fetch failed for {coin}: {e}")
        return None


def get_coinbase_rsi(coin: str, period: int = RSI_PERIOD) -> Optional[float]:
    """
    Compute simple RSI from Coinbase price history.
    Reads from local price history file (written by a price fetcher).
    """
    rsi_file = "/home/ubuntu/.openclaw/workspace/workers/coinbase/last_prices.json"
    if not os.path.exists(rsi_file):
        return None
    try:
        with open(rsi_file) as f:
            data = json.load(f)
        prices = data.get(coin, {}).get('prices', [])
        if len(prices) < period + 1:
            return None
        closes = [p.get('price', p) if isinstance(p, dict) else p for p in prices[-(period+1):]]
        if not all(isinstance(c, (int, float)) for c in closes):
            return None
        gains = []
        losses = []
        for i in range(1, len(closes)):
            delta = closes[i] - closes[i-1]
            if delta > 0:
                gains.append(delta)
            else:
                losses.append(abs(delta))
        avg_gain = sum(gains) / period if gains else 0.0
        avg_loss = sum(losses) / period if losses else 0.0
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return rsi
    except Exception:
        return None


def get_coinbase_bias(coin: str) -> str:
    """Get Coinbase bias from fetcher output."""
    bias_file = "/home/ubuntu/.openclaw/workspace/workers/coinbase/last_bias.json"
    if os.path.exists(bias_file):
        try:
            with open(bias_file) as f:
                biases = json.load(f)
                return biases.get(coin, 'neutral')
        except (json.JSONDecodeError, IOError):
            return 'neutral'
    return 'neutral'


class Strategy:
    MOMENTUM = "momentum"
    FIRST_CROSS = "first_cross"
    NONE = "none"


class StrategyTracker:
    """Tracks win rate per strategy for Kelly sizing."""

    def __init__(self, tracked_trades: int = 50):
        self.tracked_trades = tracked_trades
        self._history: Dict[str, List] = {
            Strategy.MOMENTUM: [],
            Strategy.FIRST_CROSS: [],
        }

    def record_trade(self, strategy: str, pnl: float):
        """Record trade result."""
        won = pnl > 0
        if strategy in self._history:
            self._history[strategy].append((pnl, won))
            # Keep only recent trades
            if len(self._history[strategy]) > self.tracked_trades:
                self._history[strategy] = self._history[strategy][-self.tracked_trades:]

    def get_kelly_pct(self, strategy: str) -> float:
        """Calculate Kelly % based on historical performance."""
        history = self._history.get(strategy, [])
        if len(history) < 3:
            return FIXED_KELLY_PCT  # Use default if not enough data

        wins = [pnl for pnl, won in history if won]
        losses = [pnl for pnl, won in history if not won]

        total = len(history)
        win_count = len(wins)
        W = win_count / total

        avg_win = sum(wins) / len(wins) if wins else 1.0
        avg_loss = abs(sum(losses) / len(losses)) if losses else 1.0

        if avg_loss == 0:
            return FIXED_KELLY_PCT

        R = avg_win / avg_loss
        kelly_pct = (W * (R + 1) - 1) / R

        kelly_pct = min(kelly_pct, KELLY_MAX_CAP)
        if kelly_pct <= 0:
            kelly_pct = FIXED_KELLY_PCT

        return kelly_pct


@dataclass
class TradeSignal:
    """Represents a trading signal."""
    strategy: str
    condition_id: str
    question: str
    side: str       # 'yes' or 'no'
    price: float    # Entry price
    size: float     # Dollar amount to risk
    reason: str
    confidence: int = 50
    trailing_stop_pct: float = TRAILING_BUFFER_PCT
    trailing_stop_trigger_pct: float = TRAILING_TRIGGER_PCT


@dataclass
class Position:
    """Represents an open position."""
    condition_id: str
    side: str
    entry_price: float
    contracts: float
    size: float
    open_time: float
    strategy: str
    peak_price: float = 0.0
    trailing_stop_active: bool = False


class StrategyEngine:
    """
    Polymarket momentum matrix strategy engine.

    Signal components:
    1. Price Position - entry price relative to $0.50 midpoint
    2. RSI - Coinbase 4-period RSI (oversold/overbought)
    3. Bias - Coinbase trend bias (bullish/bearish/neutral)

    Matrix combines time-in-market + price distance to decide:
    - YES or NO entry
    - Position size ($)
    - Confidence boost
    """

    def __init__(self, cash_available: float):
        self.cash = cash_available
        self.tracker = StrategyTracker()
        self._market_ages: Dict[str, float] = {}  # Track when we first saw each market

    def update_cash(self, cash: float):
        """Update available cash for sizing."""
        self.cash = cash

    def record_trade_result(self, strategy: str, pnl: float):
        """Record trade result for Kelly tracking."""
        self.tracker.record_trade(strategy, pnl)
        kelly = self.tracker.get_kelly_pct(strategy)
        logger.info(f"Strategy {strategy} Kelly: {kelly:.2%}")

    def calculate_size(
        self,
        strategy: str,
        price: float,
        confidence: int
    ) -> Tuple[float, int]:
        """
        Calculate position size using Kelly criterion + confidence multiplier.

        Returns (dollar_amount, contracts).
        """
        if confidence < 40:
            return 0.0, 0

        if price <= 0:
            return 0.0, 0

        kelly_pct = self.tracker.get_kelly_pct(strategy)

        # Confidence multiplier
        if confidence >= 80:
            conf_mult = 1.0
        elif confidence >= 60:
            conf_mult = 0.75
        elif confidence >= 40:
            conf_mult = 0.50
        else:
            return 0.0, 0

        effective_pct = kelly_pct * conf_mult
        effective_pct = min(effective_pct, KELLY_MAX_CAP)

        dollar_amount = self.cash * effective_pct
        dollar_amount = max(MIN_BET, min(MAX_BET, dollar_amount))

        contracts = dollar_amount / price

        return round(dollar_amount, 2), int(contracts)

    def get_entry_signal(
        self,
        time_minutes: float,
        price_distance_pct: float
    ) -> Tuple[str, float, int]:
        """
        Entry/Exit Matrix lookup (simplified from Superbot).

        Returns: (action, size_dollars, conf_boost)
        - action: "yes", "no", or "skip"
        - size_dollars: position size
        - conf_boost: confidence boost
        """
        # Skip if too close to expiry
        if time_minutes >= 4.5:  # 4.5+ min in
            return "skip", 0, 0

        # Time bucket
        if time_minutes <= 1:
            time_bucket = "0-1"
        elif time_minutes <= 2.5:
            time_bucket = "1-2.5"
        elif time_minutes <= 4:
            time_bucket = "2.5-4"
        else:
            time_bucket = "4-4.5"

        # Price distance bucket
        if price_distance_pct <= 10:
            dist_bucket = "0-10"
        elif price_distance_pct <= 20:
            dist_bucket = "10-20"
        elif price_distance_pct <= 30:
            dist_bucket = "20-30"
        elif price_distance_pct <= 40:
            dist_bucket = "30-40"
        else:
            dist_bucket = "40+"

        # Entry matrix (simplified for 5-min markets)
        matrix = {
            "0-1": {
                "0-10": ("skip", 0, 0),
                "10-20": ("skip", 0, 0),
                "20-30": ("med", 3.0, 5),
                "30-40": ("med", 4.0, 7),
                "40+": ("skip", 0, 0),
            },
            "1-2.5": {
                "0-10": ("skip", 0, 0),
                "10-20": ("low", 1.5, 0),
                "20-30": ("med", 3.5, 5),
                "30-40": ("low", 2.0, 0),
                "40+": ("skip", 0, 0),
            },
            "2.5-4": {
                "0-10": ("skip", 0, 0),
                "10-20": ("med", 3.0, 5),
                "20-30": ("high", 5.0, 10),
                "30-40": ("med", 3.0, 5),
                "40+": ("skip", 0, 0),
            },
            "4-4.5": {
                "0-10": ("skip", 0, 0),
                "10-20": ("low", 1.5, 0),
                "20-30": ("skip", 0, 0),
                "30-40": ("skip", 0, 0),
                "40+": ("skip", 0, 0),
            },
        }

        cell = matrix[time_bucket][dist_bucket]
        action, base_size, conf_boost = cell

        # Add slight randomness to size
        if action == "low":
            size = random.uniform(1.0, 2.0)
        elif action == "med":
            size = random.uniform(3.0, 4.0)
        elif action == "high":
            size = random.uniform(4.5, 6.0)
        else:
            size = 0

        return action, round(size, 2), conf_boost

    def evaluate_market(
        self,
        market,
        coin: str = None
    ) -> Optional[TradeSignal]:
        """
        Evaluate a Polymarket binary for trading signals.

        Uses the momentum matrix:
        1. Price position relative to $0.50
        2. RSI from Coinbase
        3. Bias from Coinbase

        Only fires when matrix says YES/NO, not SKIP.
        """
        mid_price = market.mid_price()
        time_left = market.time_to_expiry_sec()
        market_age_sec = time.time() - self._market_ages.get(market.id, time.time())

        # Track market age on first evaluation
        if market.id not in self._market_ages:
            self._market_ages[market.id] = time.time()

        logger.debug(
            f"Evaluating {market.id}: price=${mid_price:.4f}, "
            f"time_left={time_left:.0f}s, age={market_age_sec:.0f}s"
        )

        # Entry price filter
        if not (MIN_ENTRY_PRICE <= mid_price <= MAX_ENTRY_PRICE):
            logger.debug(f"{market.id}: Entry price ${mid_price:.4f} outside range - SKIP")
            return None

        # Grace period
        if market_age_sec < GRACE_PERIOD_SEC:
            logger.debug(f"{market.id}: In grace period ({market_age_sec:.0f}s) - SKIP")
            return None

        # Time filter
        if time_left < MIN_TIME_LEFT_SEC:
            logger.debug(f"{market.id}: Only {time_left:.0f}s left - SKIP")
            return None

        # Extract coin from question if not provided
        if coin is None:
            question_lower = market.question.lower()
            if "btc" in question_lower or "bitcoin" in question_lower:
                coin = "BTC"
            elif "eth" in question_lower or "ethereum" in question_lower:
                coin = "ETH"
            elif "sol" in question_lower or "solana" in question_lower:
                coin = "SOL"
            else:
                # Can't determine coin - skip
                return None

        # Get momentum indicators
        bias = get_coinbase_bias(coin)
        rsi = get_coinbase_rsi(coin)
        coin_price = get_coinbase_price(coin)

        # Calculate price distance from midpoint
        price_distance_pct = abs(mid_price - 0.50) * 100

        # Time in market
        time_minutes = (MARKET_DURATION_SEC - time_left) / 60.0

        # === MOMENTUM SIGNAL GENERATION ===
        momentum_signal = False
        momentum_side = None
        momentum_reason = None
        momentum_conf = 50

        # Condition 1: Coinbase bias + price alignment
        if bias != 'neutral':
            if bias == 'bullish' and mid_price >= 0.50:
                momentum_signal = True
                momentum_side = 'yes'
                momentum_reason = f'bullish bias + above midpoint'
                momentum_conf = 65
            elif bias == 'bearish' and mid_price <= 0.50:
                momentum_signal = True
                momentum_side = 'no'
                momentum_reason = f'bearish bias + below midpoint'
                momentum_conf = 65

        # Condition 2: RSI extremes
        if not momentum_signal and rsi is not None:
            if rsi < RSI_OVERSOLD and mid_price <= 0.80:
                momentum_signal = True
                momentum_side = 'yes'
                momentum_reason = f'RSI oversold ({rsi:.1f})'
                momentum_conf = 70
            elif rsi > RSI_OVERBOUGHT and mid_price >= 0.20:
                momentum_signal = True
                momentum_side = 'no'
                momentum_reason = f'RSI overbought ({rsi:.1f})'
                momentum_conf = 70

        # Condition 3: Price at extreme
        if not momentum_signal:
            if mid_price <= 0.30:
                momentum_signal = True
                momentum_side = 'yes'
                momentum_reason = f'price extreme oversold (${mid_price:.4f})'
                momentum_conf = 60
            elif mid_price >= 0.70:
                momentum_signal = True
                momentum_side = 'no'
                momentum_reason = f'price extreme overbought (${mid_price:.4f})'
                momentum_conf = 60

        if not momentum_signal:
            return None

        # === CHECK ENTRY MATRIX ===
        matrix_action, matrix_size, matrix_conf_boost = self.get_entry_signal(
            time_minutes, price_distance_pct
        )

        if matrix_action == "skip":
            logger.info(
                f"MOMENTUM SKIPPED (MATRIX): {market.id} | "
                f"Side: {momentum_side} | time={time_minutes:.1f}min | "
                f"dist={price_distance_pct:.1f}% | Matrix: SKIP"
            )
            return None

        # Build signal
        confidence = momentum_conf + matrix_conf_boost

        # Use matrix size if provided, else calculate
        if matrix_size > 0:
            dollar_size = matrix_size
        else:
            dollar_size, contracts = self.calculate_size(
                Strategy.MOMENTUM, mid_price, confidence
            )
            if dollar_size <= 0:
                return None

        logger.info(
            f"MOMENTUM SIGNAL: {market.id} | {momentum_side.upper()} @ ${mid_price:.4f} | "
            f"size=${dollar_size:.2f} | CONF={confidence} | "
            f"Matrix: {time_minutes:.1f}min/{price_distance_pct:.1f}% = {matrix_action.upper()} | "
            f"Bias={bias} | RSI={rsi} | age={market_age_sec:.0f}s"
        )

        return TradeSignal(
            strategy=Strategy.MOMENTUM,
            condition_id=market.id,
            question=market.question,
            side=momentum_side,
            price=mid_price,
            size=dollar_size,
            reason=f"MOMENTUM: {momentum_reason}, Bias={bias}, RSI={rsi}, "
                   f"CONF={confidence}, matrix={time_minutes:.1f}min/{price_distance_pct:.1f}%",
            confidence=confidence,
            trailing_stop_pct=TRAILING_BUFFER_PCT,
            trailing_stop_trigger_pct=TRAILING_TRIGGER_PCT,
        )

    def check_position_exit(
        self,
        position: Position,
        current_price: float,
        time_left: float
    ) -> Tuple[bool, str]:
        """
        Check if position should be exited.

        Uses trailing stop logic:
        - Trigger after 30% profit
        - Exit if price retraces 40% from peak
        """
        # Near expiry check
        if time_left <= 15:  # 15 seconds left
            return True, f"Expiry: closing at ${current_price:.4f}"

        # Calculate current profit
        if position.side == "yes":
            profit_pct = (current_price - position.entry_price) / position.entry_price
        else:
            profit_pct = (position.entry_price - current_price) / position.entry_price

        # Check if trailing stop should activate
        if not position.trailing_stop_active:
            if profit_pct >= TRAILING_TRIGGER_PCT:
                position.trailing_stop_active = True
                position.peak_price = current_price
                logger.info(
                    f"{position.condition_id}: Trailing stop ACTIVE @ ${current_price:.4f}, "
                    f"profit={profit_pct:.1%}"
                )

        # Check trailing stop hit
        if position.trailing_stop_active:
            if position.side == "yes":
                if current_price > position.peak_price:
                    position.peak_price = current_price
                else:
                    drop = (position.peak_price - current_price) / position.peak_price
                    if drop >= TRAILING_BUFFER_PCT:
                        locked_pct = (current_price - position.entry_price) / position.entry_price
                        logger.info(
                            f"{position.condition_id}: Trailing STOP HIT @ ${current_price:.4f}, "
                            f"locked={locked_pct:.1%}"
                        )
                        return True, f"Trailing stop: locked {locked_pct:.1%}"
            else:  # no
                if current_price < position.peak_price or position.peak_price == 0:
                    position.peak_price = current_price
                else:
                    rise = (current_price - position.peak_price) / position.peak_price
                    if rise >= TRAILING_BUFFER_PCT:
                        locked_pct = (position.entry_price - current_price) / position.entry_price
                        logger.info(
                            f"{position.condition_id}: Trailing STOP HIT @ ${current_price:.4f}, "
                            f"locked={locked_pct:.1%}"
                        )
                        return True, f"Trailing stop: locked {locked_pct:.1%}"

        return False, ""

    def reset_market(self, market_id: str):
        """Reset state when market expires/closes."""
        if market_id in self._market_ages:
            del self._market_ages[market_id]
