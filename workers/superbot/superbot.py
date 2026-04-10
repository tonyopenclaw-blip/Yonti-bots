#!/usr/bin/env python3
# superbot.py - Superbot Main Trading Engine
# Paper trading for Kalshi 15-minute crypto binary options
# Multi-coin: BTC, ETH, SOL, XRP, DOGE, HYPE, BNB

import json
import logging
import math
import os
import signal
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import requests

from config import (
    LOG_FILE, LOG_LEVEL, LOG_FORMAT, LOG_DATE_FORMAT,
    PAPER_MODE, PAPER_BALANCE, BALANCE_FLOOR, BALANCE_RESET_AMOUNT,
    IDLE_POLL_INTERVAL_SEC, ACTIVE_POLL_INTERVAL_SEC, MAX_OPEN_POSITIONS, MAX_BET,
    KALSHI_ACCESS_KEY, COINS, SERIES_TICKERS,
    COOLDOWN_CYCLES, DAILY_STOP_LOSS_PCT,
    COINBASE_API, COINBASE_PRODUCTS
)
from kalshi_api import KalshiAPI, Market
from strategies import StrategyEngine, Strategy, Position, TradeSignal
from report import ReportGenerator, Trade

# Candle watcher signals file - per-coin signal files to avoid collision
def get_candle_signal_file(coin: str) -> Path:
    d = Path(__file__).parent / "candle_signals"
    d.mkdir(exist_ok=True)
    return d / f"{coin}.json"

CANDLE_SIGNAL_MAX_AGE_SEC = 600  # 10 minutes (candle watcher fires every ~15 min)

# =============================================================================
# LOGGING SETUP
# =============================================================================

def setup_logging():
    """Configure logging to file and console."""
    LOG_FILE.parent.mkdir(exist_ok=True)

    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL),
        format=LOG_FORMAT,
        datefmt=LOG_DATE_FORMAT,
        handlers=[
            logging.FileHandler(LOG_FILE),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()


# =============================================================================
# NERD v2 STRATEGY CONSTANTS
# =============================================================================
MAX_POSITIONS = 3           # Max 3 concurrent positions (was 5)
MAX_DAILY_LOSS = 99999.00  # DISABLED - no daily loss limit
MAX_DAILY_TRADES = 9999     # No limit      # Max 30 trades per calendar day


class CoinbasePreFilter:
    """
    Pre-filters signals using free Coinbase data.
    Polls Coinbase every 10 seconds (no rate limit).
    Only calls Kalshi when a cross is detected.

    This dramatically reduces Kalshi API calls (from 200+ to ~50 per hour).
    """

    def __init__(self):
        self.last_prices: Dict[str, float] = {}
        self.midpoint = 0.50
        self.poll_interval = 10  # seconds
        self.last_poll = 0
        self.cross_detected: Dict[str, Optional[str]] = {}  # coin -> 'up', 'down', or None
        self._coinbase_products = COINBASE_PRODUCTS

    def check_cross(self, coin: str) -> Optional[str]:
        """
        Check if Coinbase price crossed the midpoint.
        Returns 'up', 'down', or None.
        """
        if time.time() - self.last_poll < self.poll_interval:
            return self.cross_detected.get(coin)

        product_id = self._coinbase_products.get(coin.upper())
        if not product_id:
            return None

        try:
            url = f"{COINBASE_API}/products/{product_id}/ticker"
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            data = response.json()
            price = float(data.get('price', 0))

            self.last_poll = time.time()

            if coin not in self.last_prices:
                self.last_prices[coin] = price
                self.cross_detected[coin] = None
                return None

            prev = self.last_prices[coin]
            self.last_prices[coin] = price

            # Detect cross
            if prev <= self.midpoint and price > self.midpoint:
                self.cross_detected[coin] = 'up'
                logger.debug(f"COINBASE PRE-FILTER: {coin} crossed UP @ ${price:.2f}")
            elif prev >= self.midpoint and price < self.midpoint:
                self.cross_detected[coin] = 'down'
                logger.debug(f"COINBASE PRE-FILTER: {coin} crossed DOWN @ ${price:.2f}")
            else:
                self.cross_detected[coin] = None

            return self.cross_detected.get(coin)

        except Exception as e:
            logger.debug(f"COINBASE PRE-FILTER: Error fetching {coin}: {e}")
            return None

    def get_price(self, coin: str) -> Optional[float]:
        """Get the last known Coinbase price for a coin."""
        return self.last_prices.get(coin)

    def reset_cross(self, coin: str):
        """Reset the cross detection for a coin (when market expires)."""
        self.cross_detected[coin] = None


class CoinTrader:
    """Manages trading for a single coin with independent position tracking."""

    def __init__(self, coin: str, series_ticker: str, strategy_engine: StrategyEngine, api: KalshiAPI, report: ReportGenerator):
        self.coin = coin
        self.series_ticker = series_ticker
        self.strategy_engine = strategy_engine
        self.api = api
        self.report = report

        # Per-coin position tracking
        self.positions: Dict[str, Position] = {}  # ticker -> Position
        self.cash = 0.0  # Per-coin cash tracking (managed by SuperBot)

        # Cooldown tracking: cycles since last position closed
        # After closing a position, wait COOLDOWN_CYCLES before re-entering
        self.cycles_since_close = COOLDOWN_CYCLES * 2  # Start ready to trade (multiply by 2 to be safe)

        logger.info(f"CoinTrader initialized for {coin} ({series_ticker})")

    def _cancel_orders_for_ticker(self, ticker: str):
        """Cancel all unfilled orders for a given ticker to avoid double exposure."""
        try:
            open_orders = self.api.get_open_orders()
            for order in open_orders:
                if order.get("ticker") == ticker:
                    order_id = order.get("order_id") or order.get("id")
                    if order_id:
                        result = self.api.cancel_order(order_id)
                        if "error" in result:
                            logger.warning(f"[{self.coin}] Failed to cancel order {order_id} for {ticker}: {result['error']}")
                        else:
                            logger.info(f"[{self.coin}] Canceled unfilled order {order_id} for {ticker}")
        except Exception as e:
            logger.warning(f"[{self.coin}] Error canceling orders for {ticker}: {e}")

    def get_scanner_markets(self) -> List[dict]:
        """
        Read markets from Searcher/Scanner output file.
        Returns list of market dicts from scanner's live_markets.json.
        Returns empty list if scanner hasn't run or file is stale (>5 min).
        """
        scanner_file = Path(__file__).parent.parent.parent / "data" / "live_markets.json"
        if not scanner_file.exists():
            return []

        try:
            with open(scanner_file, 'r') as f:
                data = json.load(f)

            # Check if scanner data is fresh (within 5 minutes)
            updated_at = data.get('updated_at', '')
            if updated_at:
                try:
                    scanner_time = datetime.fromisoformat(updated_at.replace('Z', ''))
                    age = datetime.now() - scanner_time.replace(tzinfo=None)
                    if age > timedelta(minutes=5):
                        logger.debug(f"[{self.coin}] Scanner data is stale ({age.total_seconds():.0f}s old)")
                        return []
                except Exception:
                    pass

            # Get markets for this coin's series
            markets_by_series = data.get('markets', {})
            scanner_markets = markets_by_series.get(self.coin, [])

            if scanner_markets:
                logger.debug(f"[{self.coin}] Found {len(scanner_markets)} markets from Scanner")

            return scanner_markets
        except Exception as e:
            logger.debug(f"[{self.coin}] Error reading scanner file: {e}")
            return []

    def get_markets(self) -> List[Market]:
        """
        Fetch markets for this coin's series.
        Uses Searcher/Scanner output if available and fresh, otherwise falls back to direct API.
        Scanner filters for tradeable markets (has price, not finalized, not expired).
        """
        # First, try Searcher/Scanner - it filters for tradeable markets only
        scanner_markets = self.get_scanner_markets()

        if scanner_markets:
            # Convert scanner market dicts to Market objects
            markets = []
            for m in scanner_markets:
                try:
                    market = Market(
                        ticker=m.get('ticker', ''),
                        yes_bid=float(m.get('yes_bid', 0)),
                        yes_ask=float(m.get('yes_ask', 0)),
                        status=m.get('status', 'open'),
                        close_time=m.get('close_time', ''),
                        series_ticker=self.series_ticker
                    )
                    markets.append(market)
                except Exception as e:
                    logger.debug(f"[{self.coin}] Error converting scanner market: {e}")

            if markets:
                logger.info(f"[{self.coin}] Using {len(markets)} markets from Searcher/Scanner")
                return markets

        # Fall back to direct API call - only open markets
        return self.api.get_open_markets(series_ticker=self.series_ticker)

    def _check_existing_positions(self, markets: Dict[str, Market]) -> bool:
        """Check open positions for exit conditions. Returns True if positions changed."""
        positions_changed = False
        for position_key, position in list(self.positions.items()):
            # Extract ticker and side from position_key (format: "ticker_side")
            ticker = position.ticker
            side = position.side
            market = markets.get(ticker)

            # Market not in current series - check if it expired
            if market is None:
                # Try to fetch the market directly to check its status
                market = self.api.get_market_by_ticker(ticker)
                if market is None:
                    # Market not found at all - treat as expired at mid price 0.5
                    logger.warning(f"[{self.coin}] Market {ticker} not found - treating as expired")
                    self._close_position(ticker, "expired", 0.5, side=side)
                    positions_changed = True
                    continue

                # FIX 1: Add try/except for time_to_expiry_sec crash loop
                try:
                    market_time_left = market.time_to_expiry_sec()
                except (AttributeError, TypeError):
                    market_time_left = 900  # Default to 15 min if method fails
                if market.status in ("closed", "settled") or market_time_left <= 0:
                    # Nerd's fix: use actual settlement result for P&L, not mid-price
                    # For settled markets, YES resolution = 1.0, NO resolution = 0.0
                    settlement_result = self.api.get_market_result(ticker)
                    if settlement_result:
                        # Use actual settlement price for accurate P&L
                        exit_price = 1.0 if settlement_result == "yes" else 0.0
                        logger.info(f"[{self.coin}] Market {ticker} settled (result={settlement_result}) - closing at {exit_price:.4f}")
                    else:
                        # Fallback to mid-price if settlement not available
                        exit_price = (market.yes_bid + market.yes_ask) / 2 if market.yes_bid > 0 else 0.5
                        logger.info(f"[{self.coin}] Market {ticker} expired (status={market.status}) - closing at {exit_price:.4f}")
                    self._close_position(ticker, "settled", exit_price, side=side)
                    positions_changed = True
                    continue
                else:
                    # Market still open but not in our markets dict - skip for now
                    continue

            mid_price = (market.yes_bid + market.yes_ask) / 2
            # FIX 1: Add try/except for time_to_expiry_sec crash loop
            try:
                time_left = market.time_to_expiry_sec()
            except (AttributeError, TypeError):
                time_left = 900  # Default to 15 min if method fails

            # Check if expired
            if time_left <= 0:
                # Nerd's fix: use actual settlement for accurate P&L
                settlement_result = self.api.get_market_result(ticker)
                if settlement_result:
                    exit_price = 1.0 if settlement_result == "yes" else 0.0
                else:
                    exit_price = mid_price
                self._close_position(ticker, "settled", exit_price, side=side)
                positions_changed = True
                continue

            # CANDLE-DURATION POSITIONS: No SL/TP - hold to expiry only
            # Skip trailing stop and 3-min rule for candle-duration positions
            if position.is_candle_duration:
                # Only exit on actual expiry or settlement
                continue

            # Check TP/SL for non-candle-duration positions (includes trailing stop logic)
            should_exit, reason = self.strategy_engine.check_position_exit(position, mid_price, time_left)
            if should_exit:
                self._close_position(ticker, reason, mid_price, side=side)
                positions_changed = True
                continue

            # === LAST 3 MINUTE RULES: Lock in profits or cut losses at extremes ===
            # If we're in the last 3 minutes and price is at extreme levels, exit immediately
            # ONLY for non-candle-duration positions (candle-duration holds to expiry)
            if time_left <= 180:  # 3 minutes or less
                if mid_price >= 0.97:
                    self._close_position(ticker, "last3_tp_97", mid_price, side=side)
                    positions_changed = True
                    continue
                if mid_price <= 0.01:
                    self._close_position(ticker, "last3_sl_01", mid_price, side=side)
                    positions_changed = True
                    continue

            # === EXTREME ZONE SCALE-IN: Scale in at extreme prices by confidence ===
            should_extreme, zone = position.should_extreme_scale_in(mid_price)
            if should_extreme:
                # Scale in +1 contract for extreme zones
                extreme_size = 1.0
                if position.side == "yes":
                    extreme_cost = mid_price * extreme_size
                else:
                    extreme_cost = (1 - mid_price) * extreme_size
                    
                if extreme_cost <= self.cash:
                    extreme_order = self.api.place_order(
                        ticker=ticker,
                        side=position.side,
                        price=mid_price,
                        amount=extreme_cost,
                        action=position.direction
                    )
                    if "error" in extreme_order:
                        logger.warning(f"[{self.coin}] Extreme scale-in order failed: {extreme_order['error']}")
                    else:
                        position.record_extreme_scale_in(zone, mid_price)
                        self.cash -= extreme_cost
                        logger.info(f"[{self.coin}] EXTREME ZONE SCALED IN ({zone.upper()}) {position_key}: +{extreme_size:.1f} contracts @ ${mid_price:.4f}, cost=${extreme_cost:.2f}, new_size={position.size:.1f}, CONF={position.confidence}")
                else:
                    logger.debug(f"[{self.coin}] Insufficient cash for extreme scale-in: ${self.cash:.2f} < ${extreme_cost:.2f}")

            # === SCALE-IN LOGIC: Add to winning positions (confidence-based) ===
            # Check if we should scale in (add more to position)
            # Scale-in conditions:
            # 1. Position is profitable (market moving in our direction) - Tony's "RIP only, not DIP"
            # 2. Confidence >= 70% at current timeframe
            # 3. Have not already scaled in (scaled_in flag)
            # 4. scale_in_count < max_scale_ins
            # NOTE: CANDLE-DURATION positions skip this - only extreme zone scale-ins allowed
            if not position.is_candle_duration and position.should_scale_in(mid_price):
                # Get scale-in size based on confidence tiers
                scale_size = position.get_scale_in_size()
                
                # Check if we have cash for scale-in
                # Calculate cost based on side
                if position.side == "yes":
                    cost = mid_price * scale_size
                else:
                    cost = (1 - mid_price) * scale_size
                    
                if cost <= self.cash:
                    # Execute scale-in: place additional order on Kalshi
                    # Use same direction as original position
                    scale_order = self.api.place_order(
                        ticker=ticker,
                        side=position.side,
                        price=mid_price,
                        amount=cost,
                        action=position.direction  # Same direction as original position
                    )
                    if "error" in scale_order:
                        logger.warning(f"[{self.coin}] Scale-in order failed: {scale_order['error']}")
                    else:
                        position.record_scale_in(mid_price, scale_size)
                        self.cash -= cost
                        logger.info(f"[{self.coin}] SCALED IN {position_key}: +{scale_size:.1f} contracts @ ${mid_price:.4f}, cost=${cost:.2f}, new_size={position.size:.1f}, CONF={position.confidence}")
                else:
                    logger.debug(f"[{self.coin}] Insufficient cash for scale-in: ${self.cash:.2f} < ${cost:.2f}")

        return positions_changed

    def _close_position(self, ticker: str, reason: str, exit_price: float, side: str = None):
        """Close a position and return PnL.
        
        For two-way market making, we need to know which side to close.
        If side is not provided, assumes the only position is for this ticker.
        """
        # Find the position key
        if side:
            position_key = f"{ticker}_{side}"
        else:
            # Try to find a position for this ticker (backwards compatibility)
            position_key = None
            for key in self.positions:
                if key.startswith(f"{ticker}_"):
                    position_key = key
                    break
            if position_key is None:
                return 0.0, None

        if position_key not in self.positions:
            return 0.0, None

        position = self.positions[position_key]
        side = position.side

        # For two-way market making: close by taking the opposite side of our position
        # If we BOUGHT YES, we SELL YES to close. If we SOLD YES (bought NO), we BUY YES to close.
        close_action = 'sell' if position.direction == 'buy' else 'buy'
        close_side = position.side  # Close by trading the SAME side as our position
        
        # Calculate cost to close
        if side == "yes":
            close_cost = exit_price * position.size
        else:
            close_cost = (1 - exit_price) * position.size
        
        close_result = self.api.place_order(
            ticker=ticker,
            side=close_side,
            price=exit_price,
            amount=close_cost,
            action=close_action  # 'buy' or 'sell'
        )
        if "error" in close_result:
            logger.error(f"[{self.coin}] REAL CLOSE ORDER FAILED: {close_result['error']}")
        else:
            logger.info(f"[{self.coin}] REAL CLOSE ORDER PLACED: {close_result}")

        # Use avg_price for PnL calculation (accounts for scale-ins)
        calc_price = position.avg_price if position.avg_price > 0 else position.entry_price

        # Tony's P&L formula: (exit - entry) × contracts (no fee multiplier)
        # For SELL positions, PnL is reversed: (entry - exit) * size
        if position.direction == 'buy':
            pnl = (exit_price - calc_price) * position.size
        else:  # sell position
            pnl = (calc_price - exit_price) * position.size

        if pnl >= 0:
            logger.info(f"[{self.coin}] Closed {position_key}: {reason}, PnL=${pnl:.2f}")
        else:
            logger.info(f"[{self.coin}] Closed {position_key}: {reason}, PnL=${pnl:.2f}")

        # Apply net PnL to paper balance
        self.cash += pnl

        # Record trade result for Kelly tracking
        self.strategy_engine.record_trade_result(position.strategy, pnl)

        # Record trade in report
        close_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        open_time_str = datetime.fromtimestamp(position.open_time).strftime("%Y-%m-%d %H:%M:%S UTC") if isinstance(position.open_time, (int, float)) else str(position.open_time)
        strategy_name = position.strategy.value if hasattr(position.strategy, 'value') else str(position.strategy)

        trade = Trade(
            ticker=position.ticker,
            side=position.side,
            entry_price=position.entry_price,
            exit_price=exit_price,
            size=position.size,
            pnl=pnl,
            strategy=strategy_name,
            open_time=open_time_str,
            close_time=close_time,
            exit_reason=reason,
            first_cross_direction=position.first_cross_direction  # Tony's first crossing insight
        )
        self.report.record_trade(trade, position)

        # Start cooldown: wait 2 full market cycles before re-entering
        self.cycles_since_close = 0
        logger.info(f"[{self.coin}] Position closed. Cooldown started: must wait {COOLDOWN_CYCLES} cycles before re-entering")

        del self.positions[position_key]
        return pnl, position.strategy

    def _open_position(self, signal: TradeSignal, available_cash: float) -> tuple[bool, float]:
        """
        Open a new position based on trading signal.
        For two-way market making: track positions by ticker+side (allow both YES and NO simultaneously).
        Returns (success, cost).
        """
        ticker = signal.ticker
        side = signal.side
        direction = getattr(signal, 'direction', 'buy')  # 'buy' or 'sell' (Tony's two-way market making)

        # Check if we already have a position on this specific side for this ticker
        position_key = f"{ticker}_{side}"  # Unique key per side
        if position_key in self.positions:
            return False, 0.0

        # Cancel any existing unfilled orders for this ticker before placing new one
        self._cancel_orders_for_ticker(ticker)
        
        # Check total position limit (allow up to 2 per side per coin = 4 total)
        # But for now we allow 2 positions per coin max (1 YES, 1 NO)
        if len(self.positions) >= 2:
            return False, 0.0

        # Calculate cost (signal.size is now contracts, not dollars)
        if side == "yes":
            cost = signal.price * signal.size
        else:
            cost = (1 - signal.price) * signal.size

        # Check if we have enough cash (cost is in dollars)
        if cost > available_cash:
            logger.warning(f"[{self.coin}] Insufficient cash: ${available_cash:.2f} < ${cost:.2f} (contracts={int(signal.size):d}, price={signal.price:.4f})")
            return False, 0.0

        # Get first cross direction for this ticker from strategy engine
        first_cross_dir = self.strategy_engine.first_cross.get_direction(ticker) or ""

        # Actually place the order on Kalshi FIRST, before recording locally
        # direction='sell' means we're selling an existing position (to close a short)
        # direction='buy' means we're buying to open a new position
        order_result = self.api.place_order(
            ticker=ticker,
            side=side,
            price=signal.price,
            amount=cost,  # amount = dollar cost
            action=direction  # 'buy' or 'sell'
        )
        if "error" in order_result:
            logger.error(f"[{self.coin}] REAL ORDER FAILED: {order_result['error']}")
            return False, 0.0
        else:
            logger.info(f"[{self.coin}] REAL ORDER PLACED: {order_result}")
            logger.info(f"[{self.coin}] Opened {signal.strategy.value}: {direction} {side} {ticker} @ ${signal.price:.4f}, contracts={int(signal.size):d}, cost=${cost:.2f}")

        # Only record position locally AFTER API call succeeds
        position = Position(
            ticker=ticker,
            side=side,
            direction=direction,  # Tony's two-way market making: 'buy' or 'sell'
            entry_price=signal.price,
            size=signal.size,
            open_time=time.time(),
            strategy=signal.strategy,
            take_profit=signal.take_profit,
            stop_loss=signal.stop_loss,
            first_cross_direction=first_cross_dir,
            # Use trailing stop values from TradeSignal (now 30% per Tony's request)
            trailing_stop_pct=signal.trailing_stop_pct,
            trailing_stop_active=False,
            trailing_stop_trigger_pct=signal.trailing_stop_trigger_pct,
            peak_price=signal.price,
            scale_in_count=0,
            max_scale_ins=2,  # Allow up to 2 scale-ins (max 3 contracts total)
            scale_in_size=0,  # Calculated dynamically during scale-in
            unrealized_pnl=0.0,
            avg_price=signal.price,
            use_time_scaling=getattr(signal, 'use_time_scaling', False),
            confidence=signal.confidence,  # Current confidence (for trailing stop)
            entry_confidence=signal.confidence,  # Entry confidence for scale-in decisions
            is_candle_duration=getattr(signal, 'is_candle_duration', False)  # Candle-duration positions have no SL/TP
        )
        # Use ticker_side as key to allow both YES and NO positions simultaneously
        self.positions[position_key] = position

        return True, cost

    def scan_for_signals(self, markets: List[Market], available_cash: float) -> tuple[List[TradeSignal], float]:
        """
        Scan markets and generate trading signals.
        Returns (signals, total_cost).
        """
        signals = []
        total_cost = 0.0

        # Index markets by ticker
        market_dict = {m.ticker: m for m in markets}

        # Check existing positions
        self._check_existing_positions(market_dict)

        # Skip if we already have a position in this coin
        if self.positions:
            return [], 0.0

        # Check cooldown: wait COOLDOWN_CYCLES after closing a position
        if self.cycles_since_close < COOLDOWN_CYCLES:
            logger.debug(f"[{self.coin}] Cooldown: {self.cycles_since_close}/{COOLDOWN_CYCLES} cycles - skipping")
            return [], 0.0

        # Scan for new signals
        for market in markets:
            # Skip if we already have a position
            if market.ticker in self.positions:
                continue

            # FIX 1: Add try/except for time_to_expiry_sec crash loop
            try:
                market_time_left = market.time_to_expiry_sec()
            except (AttributeError, TypeError):
                market_time_left = 900  # Default to 15 min if method fails

            # Skip if market is about to expire
            if market_time_left < 60:
                continue

            # evaluate_market returns List[TradeSignal] (can be multiple for mean-rev)
            trade_signals = self.strategy_engine.evaluate_market(market, self.coin)
            if trade_signals:
                # signal.size is already in contracts (capped at MAX_BET/entry_price in calculate_kelly_size)
                signals.extend(trade_signals)

        return signals, total_cost

    def increment_cooldown(self):
        """Increment cooldown counter for this coin after each market cycle."""
        if self.cycles_since_close < COOLDOWN_CYCLES:
            self.cycles_since_close += 1
            if self.cycles_since_close >= COOLDOWN_CYCLES:
                logger.info(f"[{self.coin}] Cooldown complete - can trade again")

    def get_status(self) -> str:
        """Get status string for this coin."""
        pos_count = len(self.positions)
        if pos_count > 0:
            pos_parts = []
            for position_key, pos in self.positions.items():
                pos_parts.append(f"{pos.side}@{pos.entry_price:.2f}")
            return f"{self.coin}: {', '.join(pos_parts)}"
        return f"{self.coin}: idle"


class Superbot:
    """
    Main trading engine for Superbot - Multi-coin version.

    Smart Polling (Recorder's Approach):
    - When NO active markets: poll ONE series per 10 seconds, cycle through all 8 coins
    - When a market IS active: poll that series every 1 second AND execute trades
    - Uses get_open_markets() which hits /markets?status=open (same as Recorder)
    """

    def __init__(self):
        self.api = KalshiAPI(KALSHI_ACCESS_KEY)

        # Create a strategy engine per coin (each with its own cash tracking)
        self.report = ReportGenerator()

        self.coin_traders: Dict[str, CoinTrader] = {}
        for coin in COINS:
            self.coin_traders[coin] = CoinTrader(
                coin=coin,
                series_ticker=SERIES_TICKERS[coin],
                strategy_engine=StrategyEngine(PAPER_BALANCE / len(COINS), api=self.api),  # Pass API for First Cross
                api=self.api,
                report=self.report
            )

        # Paper trading state - shared cash pool but $2 max per coin
        self.cash = PAPER_BALANCE

        # Shutdown flag
        self.running = True

        # Smart polling state (Recorder's approach)
        self.active_series: set = set()  # Track which series have active markets
        self.series_cycle = 0  # Cycle counter for idle polling through all coins
        self.our_series_tickers = list(SERIES_TICKERS.values())  # [KXBTC15M, KXETH15M, ...]

        # Coinbase pre-filter (Nerd v2)
        self.coinbase_filter = CoinbasePreFilter()

        # Daily stop-loss tracking (Nerd v2)
        self.day_start_balance = PAPER_BALANCE  # Balance at start of day
        self.day_start_time = datetime.now().strftime("%Y-%m-%d")  # Track day
        self.trading_stopped = False  # Flag when daily stop-loss triggered
        self.stop_loss_triggered = False  # Flag to indicate stop-loss was triggered this day
        self.sizing_reduced = False  # Flag: sizing reduced by 50% after balance drops below $80

        # Daily trade counter (Nerd v2)
        self.daily_trades = 0
        self.daily_trade_limit = MAX_DAILY_TRADES  # 30 trades per day

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        logger.info("=" * 60)
        logger.info("SUPERBOT INITIALIZED - NERD v2 STRATEGY")
        logger.info(f"Coins: {COINS}")
        logger.info(f"Tickers: {list(SERIES_TICKERS.values())}")
        logger.info(f"Starting balance: ${self.cash:.2f}")
        logger.info(f"Max positions: {MAX_POSITIONS} (was 5)")
        logger.info(f"Max bet per trade: ${MAX_BET:.2f}")
        logger.info(f"Max daily loss: ${MAX_DAILY_LOSS:.2f}")
        logger.info(f"Max daily trades: {MAX_DAILY_TRADES}")
        logger.info(f"Coinbase pre-filter: poll every 10s (FREE)")
        logger.info(f"Kalshi polling: every 30s (was 2s)")
        logger.info("STRATEGY: First Cross + Momentum BOTH (let them compete)")
        logger.info("=" * 60)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        logger.info(f"Received signal {signum}, shutting down...")
        self.running = False

    def _check_balance_reset(self):
        """Check if balance fell below floor and reset if needed."""
        if self.cash < BALANCE_FLOOR:
            logger.warning(f"Balance ${self.cash:.2f} below floor ${BALANCE_FLOOR:.2f}!")
            logger.warning(f"Resetting balance to ${BALANCE_RESET_AMOUNT:.2f}")
            self.cash = BALANCE_RESET_AMOUNT

    def _calculate_unrealized_pnl(self) -> float:
        """
        Calculate total unrealized PnL from all open positions.

        For YES positions: size * (current_price - entry_price)
        For NO positions: size * (entry_price - current_price)

        Returns total unrealized PnL (positive = profit, negative = loss).
        """
        unrealized_pnl = 0.0

        for trader in self.coin_traders.values():
            for ticker, position in trader.positions.items():
                # Get current price from market
                mkt = self.api.get_market_by_ticker(ticker)
                if mkt and mkt.yes_bid and mkt.yes_ask:
                    current_price = (mkt.yes_bid + mkt.yes_ask) / 2
                elif mkt:
                    current_price = mkt.yes_bid or mkt.yes_ask or position.entry_price
                else:
                    current_price = position.entry_price

                # Calculate unrealized PnL for this position
                if position.side == "yes":
                    pos_pnl = position.size * (current_price - position.avg_price)
                else:  # no
                    pos_pnl = position.size * (position.avg_price - current_price)

                unrealized_pnl += pos_pnl

        return unrealized_pnl

    def _check_daily_stop_loss(self):
        """
        Check if daily stop-loss triggered (Nerd v2).
        If balance drops below $80, reduce sizing by 50%.
        If balance drops below $50, stop trading for the day.

        NEW: MAX_DAILY_LOSS = $5 (stop if down $5)
        NEW: MAX_DAILY_TRADES = 9999     # No limit (stop if 30 trades)
        """
        # Check if we crossed into a new day - reset tracking
        current_day = datetime.now().strftime("%Y-%m-%d")
        if current_day != self.day_start_time:
            logger.info(f"New day detected ({current_day}). Resetting daily tracking.")
            self.day_start_time = current_day
            self.day_start_balance = self.cash
            self.trading_stopped = False
            self.stop_loss_triggered = False
            self.sizing_reduced = False
            self.daily_trades = 0
            self.trading_stopped = False

        # Check trade limit
        if self.daily_trades >= self.daily_trade_limit:
            if not self.trading_stopped:
                logger.warning(f"!!! DAILY TRADE LIMIT REACHED !!! {self.daily_trades} trades - stopping trading")
                self.trading_stopped = True
            return True

        # Check stop-loss thresholds (Nerd v2: $5 daily loss)
        # REALIZED P&L ONLY: cash - day_start_balance (unrealized open positions excluded)
        realized_pnl = self.cash - self.day_start_balance
        if False and realized_pnl <= -MAX_DAILY_LOSS:
            if not self.trading_stopped:
                logger.warning(f"!!! DAILY STOP-LOSS TRIGGERED !!! Realized P&L=${realized_pnl:.2f} (cash=${self.cash:.2f}) >= -${MAX_DAILY_LOSS:.2f} - stopping trading")
                self.trading_stopped = True
                self.stop_loss_triggered = True
            return True
        elif self.cash < 80:
            # Reduce sizing by 50%
            if not self.sizing_reduced:
                logger.warning(f"!!! SIZING REDUCED !!! Cash ${self.cash:.2f} < $80 - reducing position sizes by 50%")
                self.sizing_reduced = True
        else:
            # Reset sizing reduction if balance recovers
            if self.sizing_reduced:
                logger.info(f"Balance recovered to ${self.cash:.2f} >= $80 - restoring normal sizing")
                self.sizing_reduced = False

        return False

    def _distribute_cash_to_traders(self):
        """Distribute available cash to each coin's strategy engine."""
        # FIX 4: Force real balance pull from Kalshi API
        # If API fails (401 etc), get_balance returns 0 - we should NOT trust cached balance
        real_balance = self.api.get_balance()
        if real_balance > 0:
            if abs(real_balance - self.cash) > 0.50:
                logger.info(f"[CashSync] Synced cash from ${self.cash:.2f} to real balance ${real_balance:.2f}")
            self.cash = real_balance
        else:
            # FIX 4: API failed (likely 401 auth error) - don't trust cached balance
            # Use a conservative estimate (10% of paper balance) until API recovers
            conservative_estimate = self.cash * 0.2  # Only trust 20% of cached value
            if conservative_estimate < 5.0:
                conservative_estimate = 5.0  # Floor at $5 to avoid division issues
            logger.warning(f"[CashSync] API balance failed (auth error?) - using conservative estimate ${conservative_estimate:.2f} (was ${self.cash:.2f})")
            self.cash = conservative_estimate

        per_coin_cash = self.cash / len(COINS)
        for trader in self.coin_traders.values():
            trader.cash = per_coin_cash  # Initialize per-coin cash for scale-in logic
            trader.strategy_engine.update_cash(self.cash)

    def _get_coin_from_series(self, series_ticker: str) -> Optional[str]:
        """Extract coin from series_ticker (e.g., KXBTC15M -> BTC)."""
        for coin, ticker in SERIES_TICKERS.items():
            if ticker == series_ticker:
                return coin
        return None

    def _read_candle_signal(self, coin: str) -> Optional[Dict]:
        """Read a fresh candle signal from candle_watcher output file for the given coin."""
        signal_file = get_candle_signal_file(coin)
        if not signal_file.exists():
            return None
        try:
            with open(signal_file, "r") as f:
                signal_data = json.load(f)
            # Check if signal is fresh (within 5 min)
            ts_str = signal_data.get("timestamp", "")
            if ts_str:
                try:
                    signal_time = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                    # Handle case where replace didn't help (no Z present)
                    if signal_time.tzinfo is None:
                        signal_time = signal_time.replace(tzinfo=None)
                    age = datetime.utcnow() - signal_time
                    if age.total_seconds() > CANDLE_SIGNAL_MAX_AGE_SEC:
                        logger.debug(f"Candle signal stale ({age.total_seconds():.0f}s old), ignoring")
                        return None
                except Exception as e:
                    logger.debug(f"Error parsing candle signal timestamp '{ts_str}': {e}")
                    return None
            return signal_data
        except Exception as e:
            logger.debug(f"Error reading candle signal file: {e}")
            return None

    def _clear_candle_signal(self, coin: str):
        """Clear the candle signal file for the given coin after execution."""
        signal_file = get_candle_signal_file(coin)
        try:
            if signal_file.exists():
                signal_file.unlink()
                logger.info(f"Candle signal file cleared for {coin}")
        except Exception as e:
            logger.warning(f"Failed to clear candle signal file: {e}")

    def _execute_candle_signal(self, signal_data: Dict, markets: List[Market], coin: str, trader: 'CoinTrader') -> bool:
        """Execute a candle signal: find best market and place order."""
        side = signal_data.get("side", "YES").lower()  # 'yes' or 'no'
        entry_max = signal_data.get("entry_price_max", 0.85)

        # Find a suitable market
        for market in markets:
            try:
                time_left = market.time_to_expiry_sec()
            except (AttributeError, TypeError):
                time_left = 900
            if time_left < 60:
                continue

            mid = (market.yes_bid + market.yes_ask) / 2
            if mid <= 0 or mid > entry_max:
                continue

            # Build TradeSignal for candle strategy
            from strategies import TradeSignal
            ts_signal = TradeSignal(
                strategy=Strategy.MOMENTUM,
                ticker=market.ticker,
                side=side,
                direction="buy",
                price=mid,
                size=1,  # Will be sized by _open_position
                reason=f"CANDLE: {signal_data.get('coin')} {side} conf={signal_data.get('conf')}",
                is_candle_duration=True,  # No SL/TP - hold to expiry
                confidence=signal_data.get("conf", 50),
            )

            per_coin_cash = self.cash / len(COINS)
            success, cost = trader._open_position(ts_signal, per_coin_cash)
            if success:
                self.cash -= cost
                self.daily_trades += 1
                logger.info(f"🚀 [{coin}] CANDLE TRADE: {side} {market.ticker} @ ${mid:.4f} (conf={signal_data.get('conf')})")
                self._clear_candle_signal(coin)
                return True
        return False

    def _check_and_trade_series(self, series_ticker: str) -> bool:
        """
        Check a single series for tradeable markets and execute trades if found.
        Uses CoinbasePreFilter to only call Kalshi when a cross is detected.
        Polls Kalshi every 30s (was 2s) to reduce API calls.
        """
        coin = self._get_coin_from_series(series_ticker)
        if not coin:
            return False

        trader = self.coin_traders[coin]

        # === NERD v2: Coinbase pre-filter ===
        # Check Coinbase first (free, every 10s)
        # NOTE: Pre-filter is a signal boost, NOT a gate.
        # In IDLE mode, we ALWAYS call Kalshi to discover markets.
        # Pre-filter cross detection is used for trade signals, not discovery.
        coinbase_cross = self.coinbase_filter.check_cross(coin)

        has_positions = len(trader.positions) > 0

        # In IDLE mode (no active series), ALWAYS call Kalshi to discover markets
        # Don't let pre-filter block market discovery
        if not has_positions and not self.active_series:
            # IDLE mode: force Kalshi call for market discovery
            pass  # Continue to Kalshi call
        elif not has_positions and coinbase_cross is None:
            # ACTIVE mode but no positions and no Coinbase signal - still check for markets
            pass  # Continue to Kalshi call
        # else: has positions or Coinbase signal - proceed with Kalshi call

        # Use get_open_markets - hits /markets?status=open
        markets = self.api.get_open_markets(series_ticker)

        if not markets:
            # No markets found - remove from active_series
            self.active_series.discard(series_ticker)
            return False

        # Found markets! Mark this series as active
        self.active_series.add(series_ticker)

        # Index markets by ticker
        market_dict = {m.ticker: m for m in markets}

        # Check existing positions for exit conditions
        trader._check_existing_positions(market_dict)

        # === CANDLE SIGNALS: Check for fresh candle watcher signal ===
        # Check EVERY cycle (not just when no positions) - candle signals can trigger new positions
        candle_sig = self._read_candle_signal(coin)
        if candle_sig:
            sig_coin = candle_sig.get("coin")
            age = (datetime.utcnow() - datetime.fromisoformat(candle_sig.get('timestamp','').replace('Z','')).replace(tzinfo=None)).total_seconds()
            logger.info(f"[{coin}] Checking candle signal (coin={sig_coin}, age={age:.0f}s): {candle_sig}")
            executed = self._execute_candle_signal(candle_sig, markets, coin, trader)
            if executed:
                logger.info(f"[{coin}] CANDLE SIGNAL EXECUTED!")
                return True  # Candle signal executed
            else:
                logger.warning(f"[{coin}] Candle signal found but NO SUITABLE MARKET (coin={sig_coin}, markets={len(markets)})")
                for m in markets[:3]:
                    mid = (m.yes_bid + m.yes_ask) / 2
                    try: ttl=m.time_to_expiry_sec()
                    except: ttl=900
                    logger.warning(f"  Market {m.ticker}: mid={mid:.4f}, ttl={ttl:.0f}s, bid={m.yes_bid:.4f}, ask={m.yes_ask:.4f}")

        # === NERD v2: MAX_POSITIONS = 3 check ===
        total_positions = sum(len(t.positions) for t in self.coin_traders.values())
        if total_positions >= MAX_POSITIONS:
            logger.debug(f"MAX POSITIONS ({MAX_POSITIONS}) reached - not scanning for new signals")
            return True

        # Scan for NEW trading signals
        per_coin_cash = self.cash / len(COINS)

        for market in markets:
            # FIX 1: Add try/except for time_to_expiry_sec crash loop
            try:
                market_time_left = market.time_to_expiry_sec()
            except (AttributeError, TypeError):
                market_time_left = 900  # Default to 15 min if method fails

            # Skip if market is about to expire
            if market_time_left < 60:
                continue

            # Evaluate market for trading signal (returns List[TradeSignal] for mean-rev)
            trade_signals = trader.strategy_engine.evaluate_market(market, coin)
            
            for signal in trade_signals:
                # Skip if we already have a position on this side for this ticker
                # (allow YES and NO positions simultaneously for two-way market making)
                ticker_key = f"{signal.ticker}_{signal.side}"  # Unique key per side
                if ticker_key in trader.positions:
                    continue
                
                # Ensure max bet per coin is respected (AND apply sizing reduction if triggered)
                # signal.size is contracts; max_size is dollars → convert to contracts first
                max_dollar = MAX_BET
                if self.sizing_reduced:
                    max_dollar = max_dollar * 0.5  # 50% reduction
                    logger.debug(f"[{coin}] Sizing reduced: max ${max_dollar:.2f}")
                if signal.price > 0:
                    max_contracts = max_dollar / signal.price
                    signal.size = math.ceil(min(signal.size, max_contracts))

                # Try to open position
                success, cost = trader._open_position(signal, per_coin_cash)
                if success:
                    self.cash -= cost
                    self.daily_trades += 1
                    logger.info(f"🚀 [{coin}] TRADE EXECUTED: {signal.strategy.value} {signal.direction} {signal.side} {signal.ticker} @ ${signal.price:.4f}, contracts={int(signal.size):d} (daily trades: {self.daily_trades}/{MAX_DAILY_TRADES})")
                    # Don't return here - allow more trades from same market (two-way)

        return True

    def _cancel_orders_for_ticker(self, ticker: str):
        """Cancel all unfilled orders for a given ticker to avoid double exposure."""
        try:
            open_orders = self.api.get_open_orders()
            for order in open_orders:
                if order.get("ticker") == ticker:
                    order_id = order.get("order_id") or order.get("id")
                    if order_id:
                        result = self.api.cancel_order(order_id)
                        if "error" in result:
                            logger.warning(f"[{self}] Failed to cancel order {order_id} for {ticker}: {result['error']}")
                        else:
                            logger.info(f"[{self}] Canceled unfilled order {order_id} for {ticker} before new order")
        except Exception as e:
            logger.warning(f"Error canceling orders for {ticker}: {e}")

    def _cleanup_expired_orders(self):
        """
        Cancel all open orders whose markets have expired or are >15 minutes old.
        Runs at the start of each trading cycle to clean up stale resting orders.
        """
        try:
            open_orders = self.api.get_open_orders()
            if not open_orders:
                return

            canceled_count = 0
            for order in open_orders:
                ticker = order.get("ticker", "")
                order_id = order.get("order_id") or order.get("id")
                if not order_id or not ticker:
                    continue

                # Get market status to check if expired
                market = self.api.get_market_by_ticker(ticker)
                if market is None:
                    # Market no longer exists - cancel the order
                    result = self.api.cancel_order(order_id)
                    if "error" not in result:
                        logger.info(f"[ORDER CLEANUP] Canceled order {order_id} for {ticker}: market not found")
                        canceled_count += 1
                    continue

                # Cancel if market is closed/settled/expired or time has run out
                # FIX 1: Add try/except for time_to_expiry_sec crash loop
                try:
                    market_time_left = market.time_to_expiry_sec()
                except (AttributeError, TypeError):
                    market_time_left = 900  # Default to 15 min if method fails
                is_expired = market.status in ("closed", "settled") or market_time_left <= 0

                # Also cancel if order is older than 15 minutes (resting too long)
                order_time = order.get("created_at", "")
                is_stale = False
                if order_time:
                    try:
                        order_dt = datetime.fromisoformat(order_time.replace("Z", ""))
                        if order_dt.tzinfo:
                            order_dt = order_dt.replace(tzinfo=None)
                        age_minutes = (datetime.utcnow() - order_dt).total_seconds() / 60
                        is_stale = age_minutes > 15
                    except Exception:
                        pass

                if is_expired or is_stale:
                    result = self.api.cancel_order(order_id)
                    if "error" not in result:
                        reason = "market expired/settled" if is_expired else "order stale (>15min)"
                        logger.info(f"[ORDER CLEANUP] Canceled {order_id} for {ticker}: {reason}")
                        canceled_count += 1
                    else:
                        logger.warning(f"[ORDER CLEANUP] Failed to cancel {order_id}: {result.get('error')}")

            if canceled_count > 0:
                logger.info(f"[ORDER CLEANUP] Total orders canceled: {canceled_count}")
        except Exception as e:
            logger.warning(f"Error in order cleanup: {e}")

    def _poll_active_markets_fast(self):
        """
        Poll active series every 1 second - monitor positions and look for new trades.
        This is called when we have active markets.
        """
        for series_ticker in list(self.active_series):
            self._check_and_trade_series(series_ticker)

    def run(self):
        """
        Main trading loop with smart polling (Recorder's approach).

        - When NO active markets: poll ONE series per 10 seconds, cycle through all 8 coins
        - When markets ARE active: poll that series every 1 second (fast polling)
        - Cooldown: 2 full market cycles after closing any position
        - Daily stop-loss: 20% portfolio loss triggers reset
        """
        logger.info("Starting SMART POLLING trading loop (Recorder's approach)...")
        self.report.start_session()

        loop_count = 0
        last_status_log = time.time()
        last_cooldown_tick = time.time()

        while self.running:
            loop_count += 1
            try:
                # Clean up expired/stale resting orders first
                self._cleanup_expired_orders()

                # Distribute cash to each coin's strategy engine
                self._distribute_cash_to_traders()

                # Check daily stop-loss FIRST (before any trading)
                if self._check_daily_stop_loss():
                    # If stop-loss triggered, wait and continue monitoring but don't trade
                    time.sleep(IDLE_POLL_INTERVAL_SEC)
                    continue

                # Check balance floor
                self._check_balance_reset()

                # Increment cooldowns every ~15 seconds (market cycle time)
                if time.time() - last_cooldown_tick >= 15:
                    for trader in self.coin_traders.values():
                        trader.increment_cooldown()
                    last_cooldown_tick = time.time()

                if self.active_series:
                    # ACTIVE MODE: Poll all active series every 30s (was 3s)
                    # Coinbase pre-filter handles fast detection
                    for series_ticker in self.our_series_tickers:
                        self._check_and_trade_series(series_ticker)
                    time.sleep(30)  # Nerd v2: 30s Kalshi polling (was 3s)
                else:
                    # IDLE MODE: Check ONE series per cycle, cycle through all coins
                    series_ticker = self.our_series_tickers[self.series_cycle % len(self.our_series_tickers)]
                    self.series_cycle += 1

                    had_markets = self._check_and_trade_series(series_ticker)

                    if loop_count % 30 == 1:
                        # REALIZED P&L ONLY (unrealized excluded from stop-loss decisions)
                        realized_pnl = self.cash - self.day_start_balance
                        loss_pct = realized_pnl / self.day_start_balance * 100 if self.day_start_balance > 0 else 0
                        logger.info(f"😴 IDLE: checked {series_ticker} (poll #{loop_count}) | Day Realized P&L: ${realized_pnl:.2f} ({loss_pct:.1}%)")

                    # If no markets found, sleep 30 seconds
                    # If markets WERE found, don't sleep - immediately go to active polling
                    if not had_markets and not self.active_series:
                        time.sleep(30)  # Nerd v2: 30s idle poll (was 20s)

                # Status log every 30 seconds
                if time.time() - last_status_log >= 30:
                    total_positions = sum(len(t.positions) for t in self.coin_traders.values())
                    status_parts = [t.get_status() for t in self.coin_traders.values()]

                    # Build position details for the report (with live prices)
                    positions_details = []
                    for trader in self.coin_traders.values():
                        for position_key, pos in trader.positions.items():
                            # Fetch current price from Kalshi API
                            mkt = self.api.get_market_by_ticker(pos.ticker)
                            if mkt and mkt.yes_bid and mkt.yes_ask:
                                cur = (mkt.yes_bid + mkt.yes_ask) / 2
                            elif mkt:
                                cur = mkt.yes_bid or mkt.yes_ask or pos.entry_price
                            else:
                                cur = pos.entry_price

                            positions_details.append({
                                "ticker": pos.ticker,
                                "side": pos.side,
                                "direction": pos.direction,
                                "entry_price": pos.entry_price,
                                "size": pos.size,
                                "strategy": pos.strategy.value if hasattr(pos.strategy, 'value') else str(pos.strategy),
                                "open_time": datetime.fromtimestamp(pos.open_time).strftime("%Y-%m-%d %H:%M:%S UTC") if isinstance(pos.open_time, (int, float)) else str(pos.open_time),
                                "current_price": cur
                            })

                    # REALIZED P&L ONLY (unrealized excluded from stop-loss decisions)
                    realized_pnl = self.cash - self.day_start_balance
                    loss_pct = realized_pnl / self.day_start_balance * 100 if self.day_start_balance > 0 else 0

                    logger.info(f"Status: cash=${self.cash:.2f}, positions={total_positions}, loop={loop_count}, active_series={list(self.active_series)}")
                    logger.info(f"Day Realized P&L: ${realized_pnl:.2f} ({loss_pct:.1f}%) / -${MAX_DAILY_LOSS:.2f} daily stop-loss limit")
                    logger.info(f"Coins: {' | '.join(status_parts)}")

                    self.report.update_session_stats(self.cash, total_positions, positions_details)
                    last_status_log = time.time()

            except Exception as e:
                logger.error(f"Error in trading loop: {e}", exc_info=True)
                time.sleep(5)

        # Cleanup
        self._shutdown()

    def _shutdown(self):
        """Clean shutdown - close all positions and save report."""
        logger.info("Shutting down superbot...")

        # Close all open positions at current prices
        for coin, trader in self.coin_traders.items():
            for position_key, position in list(trader.positions.items()):
                logger.info(f"[{coin}] Closing position {position_key} on shutdown")
                trader._close_position(position.ticker, "shutdown", 0.5, side=position.side)

        # Save final report
        self.report.end_session(self.cash)

        logger.info("=" * 60)
        logger.info(f"FINAL BALANCE: ${self.cash:.2f}")
        logger.info(f"Total trades: {self.report.stats.total_trades}")
        logger.info(f"Report saved to: {self.report.output_file}")
        logger.info("=" * 60)


def main():
    """Entry point."""
    bot = Superbot()
    bot.run()


if __name__ == "__main__":
    main()
