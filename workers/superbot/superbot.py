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
    BASE_DIR, LOG_FILE, LOG_LEVEL, LOG_FORMAT, LOG_DATE_FORMAT,
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

def get_macro_ride_signal_file(coin: str) -> Path:
    """MACRO_RIDE signals use a separate file so they don't conflict with MACRO_FADE."""
    d = Path(__file__).parent / "candle_signals"
    d.mkdir(exist_ok=True)
    return d / f"{coin}_macro_ride.json"

CANDLE_SIGNAL_MAX_AGE_SEC = 120  # 2 minutes (signals stale after 2 min in fast markets)

SIGNAL_LOG_FILE = BASE_DIR / "signal_log.json"
SETTLEMENT_CHECK_INTERVAL_SEC = 300  # 5 minutes

# =============================================================================
# SIGNAL LOG HELPERS
# =============================================================================

def _get_signal_log() -> list:
    """Load existing signal log or empty list."""
    if SIGNAL_LOG_FILE.exists():
        try:
            with open(SIGNAL_LOG_FILE, "r") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except (json.JSONDecodeError, IOError):
            return []
    return []

def _save_signal_log(log: list):
    """Save signal log to file."""
    try:
        with open(SIGNAL_LOG_FILE, "w") as f:
            json.dump(log, f, indent=2)
    except IOError as e:
        logger.warning(f"Failed to save signal log: {e}")

def _update_signal_log(coin: str, timestamp: str, action: str, block_reason: str = None, ticker: str = None, signal_type: str = None, side: str = None):
    """
    Update action for a pending candle signal from this coin.
    Matches by coin + timestamp (PENDING → TAKEN or BLOCKED).
    If no PENDING entry exists, creates a new entry (for BLOCKED signals where CW didn't write PENDING).
    """
    log = _get_signal_log()
    updated = False
    for entry in log:
        if entry.get("coin") == coin and entry.get("timestamp") == timestamp and entry.get("action") == "PENDING":
            entry["action"] = action
            if block_reason:
                entry["block_reason"] = block_reason
            if ticker:
                entry["ticker"] = ticker
            updated = True
            break
    if not updated and action == "BLOCKED":
        # No PENDING entry found (CW didn't write one) — create BLOCKED entry directly
        new_entry = {
            "timestamp": timestamp,
            "coin": coin,
            "signal_type": signal_type or "unknown",
            "side": side or "unknown",
            "conf": 0,
            "entry_price_max": 0.85,
            "market_mid_at_signal": None,
            "action": "BLOCKED",
            "block_reason": block_reason or "unknown",
            "settlement_result": None,
            "won": None,
        }
        if ticker:
            new_entry["ticker"] = ticker
        log.append(new_entry)
        updated = True
    if updated:
        _save_signal_log(log)

def _update_settled_signals(ticker: str, settlement_result: float):
    """
    Update all pending/active signals for a ticker with settlement result.
    settlement_result: 0.0 (NO won) or 1.0 (YES won)
    """
    log = _get_signal_log()
    updated = False
    for entry in log:
        if entry.get("ticker") == ticker and entry.get("settlement_result") is None:
            entry["settlement_result"] = settlement_result
            side = entry.get("side", "").upper()
            if side == "YES":
                entry["won"] = (settlement_result == 1.0)
            elif side == "NO":
                entry["won"] = (settlement_result == 0.0)
            else:
                entry["won"] = None
            updated = True
    if updated:
        _save_signal_log(log)
        logger.info(f"SIGNAL LOG: Updated settlement for ticker {ticker}: result={settlement_result}, won={entry.get('won')}")

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
    
    TIER 1 FEATURE: Also tracks price_vs_strike_pct for signal confirmation.
    """

    def __init__(self):
        self.last_prices: Dict[str, float] = {}
        self.midpoint = 0.50
        self.poll_interval = 10  # seconds
        self.last_poll = 0
        self.cross_detected: Dict[str, Optional[str]] = {}  # coin -> 'up', 'down', or None
        self._coinbase_products = COINBASE_PRODUCTS
        # TIER 1: price_vs_strike tracking
        self.price_vs_strike_pct: Dict[str, float] = {}  # coin -> deviation from floor_strike in %
        self.floor_strikes: Dict[str, float] = {}  # coin -> floor_strike price

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

    def update_price_vs_strike(self, coin: str, floor_strike: float):
        """
        TIER 1: Update price_vs_strike_pct for a coin.
        
        price_vs_strike_pct = (coinbase_price - floor_strike) / floor_strike * 100
        
        If > 0 (BTC above strike) → YES bias
        If < 0 (BTC below strike) → NO bias
        """
        if floor_strike is None or floor_strike <= 0:
            self.price_vs_strike_pct[coin] = 0.0
            return
        
        self.floor_strikes[coin] = floor_strike
        coin_price = self.last_prices.get(coin)
        
        if coin_price is not None:
            pct = (coin_price - floor_strike) / floor_strike * 100
            self.price_vs_strike_pct[coin] = pct
            
            # Log significant deviations (>0.1%)
            if abs(pct) > 0.1:
                bias = "YES" if pct > 0 else "NO"
                logger.debug(f"PRICE_VS_STRIKE: {coin} {pct:.3f}% ({bias} bias) - coinbase=${coin_price:.2f} vs strike=${floor_strike:.2f}")

    def get_price_vs_strike_pct(self, coin: str) -> float:
        """Get the price_vs_strike_pct for a coin (0.0 if unknown)."""
        return self.price_vs_strike_pct.get(coin, 0.0)

    def get_price_vs_strike_bias(self, coin: str) -> str:
        """
        TIER 1: Get directional bias based on price_vs_strike_pct.
        Returns 'yes', 'no', or 'neutral'.
        """
        pct = self.price_vs_strike_pct.get(coin, 0.0)
        if pct > 0.05:  # >0.05% above strike → YES bias
            return 'yes'
        elif pct < -0.05:  # >0.05% below strike → NO bias
            return 'no'
        return 'neutral'

    def get_price(self, coin: str) -> Optional[float]:
        """Get the last known Coinbase price for a coin."""
        return self.last_prices.get(coin)

    def reset_cross(self, coin: str):
        """Reset the cross detection for a coin (when market expires)."""
        self.cross_detected[coin] = None


class OrderbookMonitor:
    """
    TIER 1 FEATURE: Monitors orderbook imbalance every 10 seconds.
    
    ob_imbalance = (yes_qty - no_qty) / (yes_qty + no_qty)
    
    Heavy YES imbalance (>0.3) + our signal = stronger YES entry
    Heavy NO imbalance (<-0.3) + our signal = stronger NO entry
    
    API: GET /trade-api/v2/markets/{ticker}/orderbook (no auth needed)
    """

    def __init__(self, api: KalshiAPI):
        self.api = api
        self.poll_interval = 10  # seconds
        self.last_poll: Dict[str, float] = {}  # ticker -> last poll timestamp
        self.ob_imbalance: Dict[str, float] = {}  # ticker -> imbalance (-1 to +1)
        self.yes_qty: Dict[str, float] = {}  # ticker -> total YES bid qty
        self.no_qty: Dict[str, float] = {}  # ticker -> total NO bid qty

    def update_orderbook(self, ticker: str) -> Optional[float]:
        """
        Poll orderbook for a ticker and calculate imbalance.
        Returns the ob_imbalance value or None if failed.
        """
        # Rate limit: only poll every poll_interval seconds per ticker
        last = self.last_poll.get(ticker, 0)
        if time.time() - last < self.poll_interval:
            return self.ob_imbalance.get(ticker)
        
        try:
            orderbook = self.api.get_orderbook(ticker)
            if orderbook is None:
                return self.ob_imbalance.get(ticker)
            
            self.last_poll[ticker] = time.time()
            
            # Extract YES and NO bid quantities
            # Orderbook structure: {yes_bids: [[price, size], ...], no_bids: [[price, size], ...]}
            yes_bids = orderbook.get('yes_bids', [])
            no_bids = orderbook.get('no_bids', [])
            
            # Sum up all YES and NO bid sizes
            yes_total = sum(float(bid[1]) for bid in yes_bids if len(bid) >= 2)
            no_total = sum(float(bid[1]) for bid in no_bids if len(bid) >= 2)
            
            self.yes_qty[ticker] = yes_total
            self.no_qty[ticker] = no_total
            
            # Calculate imbalance: (yes - no) / (yes + no)
            total = yes_total + no_total
            if total > 0:
                imbalance = (yes_total - no_total) / total
            else:
                imbalance = 0.0
            
            self.ob_imbalance[ticker] = imbalance
            
            # Log significant imbalances
            if abs(imbalance) > 0.15:
                side = "YES" if imbalance > 0 else "NO"
                logger.debug(f"OB_IMBALANCE: {ticker} {imbalance:.3f} ({side} heavy) - yes_qty={yes_total:.0f}, no_qty={no_total:.0f}")
            
            return imbalance
            
        except Exception as e:
            logger.debug(f"OB_IMBALANCE: Error fetching orderbook for {ticker}: {e}")
            return self.ob_imbalance.get(ticker)

    def get_imbalance(self, ticker: str) -> float:
        """Get the last known ob_imbalance for a ticker (0.0 if unknown)."""
        return self.ob_imbalance.get(ticker, 0.0)

    def get_imbalance_bias(self, ticker: str) -> str:
        """
        Get directional bias based on ob_imbalance.
        Returns 'yes', 'no', or 'neutral'.
        
        Heavy YES imbalance (>0.3) → YES bias
        Heavy NO imbalance (<-0.3) → NO bias
        Otherwise → neutral
        """
        imbalance = self.ob_imbalance.get(ticker, 0.0)
        if imbalance > 0.3:
            return 'yes'
        elif imbalance < -0.3:
            return 'no'
        return 'neutral'

    def get_imbalance_strength(self, ticker: str) -> float:
        """
        Get the strength of the imbalance signal.
        Returns a multiplier: 1.0 = neutral, >1.0 = stronger signal
        
        For YES: if imbalance > 0.3, strength = 1 + imbalance
        For NO: if imbalance < -0.3, strength = 1 + abs(imbalance)
        """
        imbalance = self.ob_imbalance.get(ticker, 0.0)
        if imbalance > 0.3:
            return 1.0 + imbalance  # e.g., 0.5 imbalance → 1.5x strength
        elif imbalance < -0.3:
            return 1.0 + abs(imbalance)
        return 1.0  # neutral

    def update_tickers(self, tickers: List[str]):
        """Update orderbooks for a list of tickers."""
        for ticker in tickers:
            self.update_orderbook(ticker)


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

            # === NEW: PRICE-LEVEL SCALE-IN & CUT-LOSS ===
            # SCALE-IN: If price >= $0.80 and we hold that side, buy $5 more (once per position)
            if mid_price >= 0.80 and not position.scaled_in and time_left <= 300:
                scale_cost = 5.0  # Fixed $5 notional
                scale_result = self.api.place_order(
                    ticker=ticker,
                    side=position.side,
                    price=mid_price,
                    amount=scale_cost,
                    action='buy'
                )
                if "error" not in scale_result:
                    position.scaled_in = True
                    logger.info(f"SCALE IN: [{self.coin}] {position.side.upper()} {ticker} added $5 at ${mid_price:.4f} (time_left={time_left}s)")
                    positions_changed = True
                else:
                    logger.warning(f"SCALE IN FAILED: [{self.coin}] {scale_result['error']}")

            # 12-MIN NO CUT-LOSS: For 12-min NO positions, cut at $0.05 (higher conviction = tighter stop)
            if getattr(position, 'is_12min_no', False) and mid_price <= 0.05 and side == "no":
                entry_price = position.avg_price if position.avg_price > 0 else position.entry_price
                logger.warning(f"12MIN CUT LOSS: [{self.coin}] NO {ticker} exited at ${mid_price:.4f} (was ${entry_price:.4f} entry)")
                self._close_position(ticker, "12min_cut_loss_no", mid_price, side=side)
                positions_changed = True
                continue

            # CUT-LOSS: If price <= $0.10 AND time_remaining <= 7.5 min, close entire position immediately
            # Nerd fix: raised from $0.20 to $0.10 - $0.20 was cutting winners prematurely (33% cut-loss rate, 0% win rate)
            # EXCEPTION: candle-duration positions hold to expiry - they would have won (BNB, SOL, HYPE, BTC, XRP all won)
            elif mid_price <= 0.10 and time_left <= 450 and not position.is_candle_duration:
                entry_price = position.avg_price if position.avg_price > 0 else position.entry_price
                logger.warning(f"CUT LOSS: [{self.coin}] {position.side.upper()} {ticker} exited at ${mid_price:.4f} (was ${entry_price:.4f} entry, time_left={time_left}s)")
                self._close_position(ticker, "cut_loss_30", mid_price, side=side)
                positions_changed = True
                continue

            # CANDLE-DURATION POSITIONS: Last 5 min trailing stop from high/low
            # If time_left <= 300s AND price in extreme zone -> trailing stop activates
            # For YES: trailing_stop = high_price - 0.20, exit when price hits
            # For NO: trailing_stop = low_price + 0.20, exit when price hits
            if position.is_candle_duration:
                if time_left <= 300:
                    # Track high/low for trailing stop
                    if not hasattr(position, '_trail_high'):
                        position._trail_high = mid_price
                        position._trail_low = mid_price
                    
                    if position.side == "yes" and mid_price >= 0.80:
                        # Update trailing high while price is in zone
                        if mid_price > position._trail_high:
                            position._trail_high = mid_price
                        trailing_stop = position._trail_high - 0.20
                        logger.debug(f"[{self.coin}] CANDLE trailing stop: YES high={position._trail_high:.4f}, stop={trailing_stop:.4f}, price={mid_price:.4f}, time_left={time_left}s")
                        if mid_price <= trailing_stop:
                            self._close_position(ticker, f"candle_trail_stop_yes", mid_price, side=side)
                            positions_changed = True
                            continue
                    elif position.side == "no" and mid_price <= 0.20:
                        # Update trailing low while price is in zone
                        if mid_price < position._trail_low:
                            position._trail_low = mid_price
                        trailing_stop = position._trail_low + 0.20
                        logger.debug(f"[{self.coin}] CANDLE trailing stop: NO low={position._trail_low:.4f}, stop={trailing_stop:.4f}, price={mid_price:.4f}, time_left={time_left}s")
                        if mid_price >= trailing_stop:
                            self._close_position(ticker, f"candle_trail_stop_no", mid_price, side=side)
                            positions_changed = True
                            continue
                # Hold to expiry otherwise
                continue

            # CANDLE-DURATION STOP-LOSS: 50% stop in final 5 minutes
            # Both YES and NO: exit if current_price <= entry_price * 0.50
            # NO entered at $0.44 → stop at $0.22. YES entered at $0.44 → stop at $0.22.
            if position.is_candle_duration and time_left <= 300:
                entry_price = position.entry_price
                stop_price = entry_price * 0.50
                if mid_price <= stop_price:
                    logger.warning(f"STOP LOSS: [{self.coin}] {position.side.upper()} entry={entry_price:.4f} current={mid_price:.4f} stop={stop_price:.4f}")
                    self._close_position(ticker, f"candle_stop_loss_{position.side}", mid_price, side=side)
                    positions_changed = True
                    continue
            # Hold to expiry otherwise
            continue

            # === SCALE-IN LOGIC: Add to positions as price moves in our favor ===
            # Check extreme zone scale-in first (higher priority)
            should_extreme, extreme_zone = position.should_extreme_scale_in(mid_price)
            if should_extreme:
                # Extreme zone scale-in: +1 contract at extreme zones
                scale_size = position.get_scale_in_size()
                if position.size + scale_size <= 3.0:  # Cap at 3 contracts
                    # Place scale-in order
                    scale_cost = mid_price * scale_size if position.side == "yes" else (1 - mid_price) * scale_size
                    scale_result = self.api.place_order(
                        ticker=ticker,
                        side=position.side,
                        price=mid_price,
                        amount=scale_cost,
                        action='buy'
                    )
                    if "error" not in scale_result:
                        position.record_extreme_scale_in(extreme_zone, mid_price)
                        logger.info(f"[{self.coin}] EXTREME SCALE-IN: {position.side} {ticker} @ ${mid_price:.4f}, +{scale_size:.1f} contracts, new_size={position.size:.1f}")
                    else:
                        logger.warning(f"[{self.coin}] EXTREME SCALE-IN FAILED: {scale_result['error']}")
                    positions_changed = True
            
            # Check regular price-level scale-in
            # Scale in when price moves $0.10+ in our favor
            elif position.should_scale_in(mid_price):
                scale_size = position.get_scale_in_size()
                if position.size + scale_size <= 3.0:  # Cap at 3 contracts
                    # Place scale-in order
                    scale_cost = mid_price * scale_size if position.side == "yes" else (1 - mid_price) * scale_size
                    scale_result = self.api.place_order(
                        ticker=ticker,
                        side=position.side,
                        price=mid_price,
                        amount=scale_cost,
                        action='buy'
                    )
                    if "error" not in scale_result:
                        position.record_scale_in(mid_price, scale_size)
                        logger.info(f"[{self.coin}] SCALE-IN: {position.side} {ticker} @ ${mid_price:.4f}, +{scale_size:.1f} contracts, new_size={position.size:.1f}")
                    else:
                        logger.warning(f"[{self.coin}] SCALE-IN FAILED: {scale_result['error']}")
                    positions_changed = True

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
        
        # CashSync state - track last known real balance for conservative estimates
        self._last_known_real_balance = 0.0
        
        # TIER 1: Orderbook monitor for imbalance tracking
        self.orderbook_monitor = OrderbookMonitor(self.api)

        # Daily stop-loss tracking (Nerd v2)
        self.day_start_balance = PAPER_BALANCE  # Balance at start of day
        self.day_start_time = datetime.now().strftime("%Y-%m-%d")  # Track day
        self.trading_stopped = False  # Flag when daily stop-loss triggered
        self.stop_loss_triggered = False  # Flag to indicate stop-loss was triggered this day
        self.sizing_reduced = False  # Flag: sizing reduced by 50% after balance drops below $80

        # Daily trade counter (Nerd v2)
        self.daily_trades = 0
        self.daily_trade_limit = MAX_DAILY_TRADES  # 30 trades per day

        # === 12-MIN NO LOCK-IN: Track window open prices per coin ===
        # window_open_prices[coin][ticker] = floor_strike at window start
        self.window_open_prices: Dict[str, Dict[str, float]] = {coin: {} for coin in COINS}
        # 12min_checked_windows[coin] = set of ticker keys already checked for 12-min entry
        self.twelvemin_checked_windows: Dict[str, set] = {coin: set() for coin in COINS}

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
        logger.info("TIER 1 FEATURES:")
        logger.info("  - price_vs_strike_pct: Coinbase vs floor_strike deviation (YES bias if >0)")
        logger.info("  - ob_imbalance: Orderbook imbalance (-1 to +1, heavy >0.3 or <-0.3)")
        logger.info("  - Entry blackout: Skip signals between 300-360s (10-11 min window)")
        logger.info("=" * 60)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        logger.info(f"Received signal {signum}, shutting down...")
        self.running = False

    def _check_and_update_settled_markets(self):
        """
        Check for settled markets and update their signal log entries.
        Runs periodically in the trading loop.
        Fix: Check pending signals directly (not just open markets) so we can
        update settlements for markets that have already dropped off the open list.
        """
        try:
            signal_file = Path(__file__).parent / "signal_log.json"
            if not signal_file.exists():
                return

            with open(signal_file) as f:
                signals = json.load(f)

            updated = False
            for sig in signals:
                # Only process TAKEN/BLOCKED signals that haven't settled yet
                if sig.get("settlement_result") is not None:
                    continue
                if sig.get("action") not in ("TAKEN", "BLOCKED"):
                    continue

                ticker = sig.get("ticker")
                if not ticker:
                    continue

                # Try to get settlement result for this ticker
                result = self.api.get_market_result(ticker)
                if result:
                    settlement_val = 1.0 if result == "yes" else 0.0
                    sig["settlement_result"] = settlement_val
                    sig["won"] = True if result == "yes" else False
                    logger.info(f"SIGNAL SETTLED: {sig.get('coin')} {sig.get('side')} {ticker} -> {result} (signal was {sig.get('action')})")
                    updated = True

            if updated:
                with open(signal_file, "w") as f:
                    json.dump(signals, f, indent=2)
        except Exception as e:
            logger.debug(f"Settlement check error: {e}")

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
            self._last_known_real_balance = real_balance  # Track last known good balance
        else:
            # FIX 4: API failed (likely 401 auth error) - use last known real balance
            # If no known balance, fall back to conservative estimate based on last known good
            if self._last_known_real_balance > 0:
                conservative_estimate = max(10.0, self._last_known_real_balance * 0.5)  # $10 floor, 50% of last known
            else:
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

    def _read_macro_ride_signal(self, coin: str) -> Optional[Dict]:
        """Read a MACRO_RIDE signal from the separate signal file."""
        signal_file = get_macro_ride_signal_file(coin)
        try:
            if not signal_file.exists():
                return None
            with open(signal_file) as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read macro ride signal file: {e}")
            return None

    def _clear_macro_ride_signal(self, coin: str):
        """Clear the MACRO_RIDE signal file after execution."""
        signal_file = get_macro_ride_signal_file(coin)
        try:
            if signal_file.exists():
                signal_file.unlink()
                logger.info(f"Macro ride signal file cleared for {coin}")
        except Exception as e:
            logger.warning(f"Failed to clear macro ride signal file: {e}")

    def _execute_candle_signal(self, signal_data: Dict, markets: List[Market], coin: str, trader: 'CoinTrader') -> bool:
        """Execute a candle signal: find best market and place order."""
        side = signal_data.get("side", "YES").lower()  # 'yes' or 'no'
        signal_type = signal_data.get("signal_type", "CANDLE")  # CANDLE or MACRO_FADE
        is_candle_duration = signal_data.get("is_candle_duration", True)

        sig_timestamp = signal_data.get("timestamp", "")
        entry_max = signal_data.get("entry_price_max", 0.85)

        # Track first viable market for block logging (so we can track outcome)
        first_viable_ticker = None
        first_viable_mid = None

        # Find a suitable market
        for market in markets:
            try:
                time_left = market.time_to_expiry_sec()
            except (AttributeError, TypeError):
                time_left = 900
            if time_left < 60:
                continue

            mid = (market.yes_bid + market.yes_ask) / 2

            # Capture first market that passes time filter (for block tracking)
            if first_viable_ticker is None:
                first_viable_ticker = market.ticker
                first_viable_mid = mid

            # For YES signals, only block absurdly expensive entries
            # $0.65 was too tight — expand to $0.75 to allow valid momentum signals
            if side == "yes" and mid > 0.75:
                logger.info(f"[{coin}] ENTRY SKIP: YES entry ${mid:.4f} > $0.75 (too expensive)")
                continue

            # For NO signals, block when YES is cheap (YES < $0.30 means market thinks YES unlikely = NO overpriced)
            # Relaxed from $0.38 to $0.30 to catch more valid fades in the $0.30-$0.50 dead zone
            if side == "no" and mid < 0.30:
                logger.info(f"[{coin}] ENTRY SKIP: NO entry ${mid:.4f} (YES=${mid:.4f} < $0.38, NO overpriced)")
                continue

            # === ENTRY PRICE GUARD: Block entries below $0.15 or above $0.85 ===
            if mid < 0.15:
                logger.info(f"[{coin}] ENTRY SKIP: entry price ${mid:.4f} < $0.15 (below minimum)")
                continue
            if mid > 0.85:
                logger.info(f"[{coin}] ENTRY SKIP: entry price ${mid:.4f} > $0.85 (above maximum)")
                continue

            # MACRO_FADE entry guard: also check mid is within sane range
            if signal_type == "MACRO_FADE":
                logger.info(f"[{coin}] MACRO_FADE: {signal_data.get('reason', 'N/A')}")

            if mid <= 0 or mid > entry_max:
                continue

            # Build TradeSignal for candle strategy
            from strategies import TradeSignal
            # Calculate Kelly-based size using confidence (same as evaluate_market path)
            prob = mid if side == "yes" else (1 - mid)
            confidence = signal_data.get("conf", signal_data.get("confidence", 50))
            size, kelly_pct, _ = trader.strategy_engine.calculate_kelly_size(
                Strategy.MOMENTUM, prob, confidence, mid, cash_override=self.cash
            )
            ts_signal = TradeSignal(
                strategy=Strategy.MOMENTUM,
                ticker=market.ticker,
                side=side,
                direction="buy",
                price=mid,
                size=int(size),
                reason=f"{signal_type}: {signal_data.get('coin', coin)} {side} conf={confidence} kelly={kelly_pct:.1%}",
                is_candle_duration=is_candle_duration,  # MACRO_FADE uses False = normal SL/TP
                confidence=confidence,
            )

            # Use Bot's full cash for Kelly sizing (not per-coin split) since we only take 1 position per coin
            available_cash = self.cash  # Full cash for Kelly calculation
            success, cost = trader._open_position(ts_signal, available_cash)
            if success:
                self.cash -= cost
                self.daily_trades += 1
                logger.info(f"🚀 [{coin}] {signal_type} TRADE: {side} {market.ticker} @ ${mid:.4f} (conf={confidence}) contracts={int(size):d}")
                _update_signal_log(coin, sig_timestamp, "TAKEN", ticker=market.ticker)
                self._clear_candle_signal(coin)
                return True

        # === Signal was blocked — log with ticker so we can track outcome ===
        # NOTE: NO signals now go through the same entry guard evaluation as YES
        # The blanket block on NO was hiding profitable signals (4 blocked NO signals would have won)
        if first_viable_ticker is None:
            block_reason = "no suitable market"
        else:
            block_reason = f"entry guard skipped (mid ${first_viable_mid:.4f})"

        _update_signal_log(coin, sig_timestamp, "BLOCKED", block_reason, ticker=first_viable_ticker, signal_type=signal_data.get("signal_type", "CANDLE"), side=side.upper())
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

        # === TIER 1: Update Coinbase price_vs_strike_pct and orderbook imbalance ===
        # Update Coinbase price_vs_strike_pct using market's floor_strike
        for market in markets:
            if market.floor_strike is not None and market.floor_strike > 0:
                self.coinbase_filter.update_price_vs_strike(coin, market.floor_strike)
        
        # Update orderbook imbalance for all markets in this series
        self.orderbook_monitor.update_tickers([m.ticker for m in markets])

        # Check existing positions for exit conditions
        trader._check_existing_positions(market_dict)

        # === CANDLE SIGNALS: Check for fresh candle watcher signal ===
        # Check EVERY cycle (not just when no positions) - candle signals can trigger new positions
        candle_sig = self._read_candle_signal(coin)
        if candle_sig:
            sig_coin = candle_sig.get("coin")
            sig_timestamp = candle_sig.get('timestamp', '')
            age = (datetime.utcnow() - datetime.fromisoformat(sig_timestamp.replace('Z','')).replace(tzinfo=None)).total_seconds()
            logger.info(f"[{coin}] Checking candle signal (coin={sig_coin}, age={age:.0f}s): {candle_sig}")
            # Write PENDING so _execute_candle_signal can update it to TAKEN/BLOCKED
            _update_signal_log(coin, sig_timestamp, "PENDING", signal_type=candle_sig.get("signal_type", "CANDLE"), side=candle_sig.get("side", "YES").upper())
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

        # === OPEN ORDER STRATEGY: Catch MACRO_FADE/PUMP at the open ===
        # If MACRO_FADE fires with 5+ coins and market just opened, try to get both YES+NO <= $0.15
        if candle_sig and candle_sig.get('signal_type') in ('MACRO_FADE', 'MACRO_PUMP'):
            cluster_coins = candle_sig.get('cluster_coins', [])
            if len(cluster_coins) >= 5:
                sig_timestamp = candle_sig.get('timestamp', '')
                try:
                    sig_dt = datetime.fromisoformat(sig_timestamp.replace('Z','')).replace(tzinfo=None)
                    sig_age = (datetime.utcnow() - sig_dt).total_seconds()
                except:
                    sig_age = 999
                
                # Only try if signal is fresh (< 20s) and we haven't tried yet
                open_order_key = (coin, sig_timestamp)
                if sig_age < 20 and open_order_key not in getattr(self, '_open_order_tried', set()):
                    if not hasattr(self, '_open_order_tried'):
                        self._open_order_tried = set()
                    self._open_order_tried.add(open_order_key)
                    
                    logger.info(f"[{coin}] OPEN ORDER: Fresh {candle_sig.get('signal_type')} with {len(cluster_coins)} coins, age={sig_age:.0f}s - checking open market...")
                    both_filled = self._place_open_orders(coin, markets, candle_sig.get('signal_type', 'MACRO_FADE'))
                    if both_filled:
                        # Open order succeeded - both sides filled cheap, we're hedged for profit
                        logger.info(f"[{coin}] OPEN ORDER: Success! Both sides filled at open. Returning.")
                        return True

        # === 12-MIN NO LOCK-IN: Check at 12 min mark (3 min remaining) ===
        # This fires once per window when time_remaining <= 180s
        self._check_12min_no_lockin(series_ticker, markets, coin, trader)

        # === MACRO_RIDE: Momentum-following paper test for 7+ coin clusters ===
        # Processed separately from MACRO_FADE via a different signal file
        macro_ride_sig = self._read_macro_ride_signal(coin)
        if macro_ride_sig:
            sig_coin = macro_ride_sig.get("coin")
            sig_timestamp = macro_ride_sig.get('timestamp', '')
            age = (datetime.utcnow() - datetime.fromisoformat(sig_timestamp.replace('Z','')).replace(tzinfo=None)).total_seconds()
            logger.info(f"[{coin}] Checking MACRO_RIDE signal (coin={sig_coin}, age={age:.0f}s): {macro_ride_sig}")
            # Write PENDING so _execute_candle_signal can update it to TAKEN/BLOCKED
            _update_signal_log(coin, sig_timestamp, "PENDING", signal_type="MACRO_RIDE", side=macro_ride_sig.get("side", "YES").upper())
            executed = self._execute_candle_signal(macro_ride_sig, markets, coin, trader)
            if executed:
                logger.info(f"[{coin}] MACRO_RIDE SIGNAL EXECUTED!")
                self._clear_macro_ride_signal(coin)
                return True
            else:
                logger.warning(f"[{coin}] MACRO_RIDE signal found but NO SUITABLE MARKET")

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
            # TIER 1: Pass price_vs_strike_pct and ob_imbalance signals
            price_vs_strike_pct = self.coinbase_filter.get_price_vs_strike_pct(coin)
            ob_imbalance = self.orderbook_monitor.get_imbalance(market.ticker)
            trade_signals = trader.strategy_engine.evaluate_market(
                market, coin,
                price_vs_strike_pct=price_vs_strike_pct,
                ob_imbalance=ob_imbalance
            )
            
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
                # EXPERIMENTAL: YES signals in $0.60-$0.65 range capped at $0.50 (watch-list test)
                if signal.side == 'yes' and signal.price > 0.60:
                    max_dollar = min(max_dollar, 0.50)
                    logger.debug(f"[{coin}] EXPERIMENTAL: YES mid ${signal.price:.4f} > $0.60 - capping at ${max_dollar:.2f}")
                # EXPERIMENTAL: CANDLE_NO signals capped at $0.50 (watch-list test)
                # CANDLE_NO is structurally fragile — treat as watch-list until we have WR data
                if signal.side == 'no' and signal.signal_type == 'candle_NO':
                    max_dollar = min(max_dollar, 0.50)
                    logger.debug(f"[{coin}] EXPERIMENTAL: CANDLE_NO ${signal.price:.4f} - capping at ${max_dollar:.2f}")
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

    def _place_open_orders(self, coin: str, markets: List[Market], signal_type: str) -> bool:
        """
        OPEN ORDER STRATEGY (Tony's edge play):
        When MACRO_FADE/PUMP fires, check if newly opened market has YES and NO both <= $0.15.
        If so, place $1 YES + $1 NO limit orders at $0.15 simultaneously.
        Wait up to 30s for fills. Cancel unfilled.
        
        This catches reversals at the open - if both sides are cheap, one side will move.
        
        Args:
            coin: coin symbol (BTC, ETH, etc.)
            markets: list of open Market objects
            signal_type: 'MACRO_FADE' or 'MACRO_PUMP'
        
        Returns:
            True if both sides filled at <= $0.15, False otherwise
        """
        OPEN_ORDER_MAX_PRICE = 0.15
        OPEN_ORDER_AMOUNT = 1.00  # $1 per side
        OPEN_ORDER_TIMEOUT = 30    # seconds to wait for fills
        OPEN_ORDER_POLL = 5       # poll every 5 seconds

        # Find the market with most time remaining (likely the newly opened one)
        market = None
        max_time = 0
        for m in markets:
            try:
                ttl = m.time_to_expiry_sec()
                if ttl > max_time:
                    max_time = ttl
                    market = m
            except (AttributeError, TypeError):
                continue
        
        if not market:
            return False
        
        ticker = market.ticker
        
        # Check if market just opened (within 60s of now based on market open_time)
        try:
            import re
            open_time_str = getattr(market, 'open_time', None) or ''
            if open_time_str:
                # Parse ISO timestamp
                open_dt = datetime.fromisoformat(open_time_str.replace('Z', '+00:00'))
                open_ts = open_dt.timestamp()
                age = time.time() - open_ts
                if age > 15:
                    logger.debug(f"[{coin}] OPEN ORDER: market age {age:.0f}s > 15s, skipping open-order check")
                    return False
                logger.info(f"[{coin}] OPEN ORDER: market {ticker} is {age:.0f}s old, checking prices...")
        except Exception as e:
            logger.debug(f"[{coin}] OPEN ORDER: couldn't parse market age: {e}")
            # Continue anyway - check prices directly
        
        # Get current prices
        yes_bid = getattr(market, 'yes_bid', None) or 0
        yes_ask = getattr(market, 'yes_ask', None) or 0
        no_bid = getattr(market, 'no_bid', None) or 0
        no_ask = getattr(market, 'no_ask', None) or 0
        
        yes_mid = (yes_bid + yes_ask) / 2 if yes_bid and yes_ask else None
        no_mid = (no_bid + no_ask) / 2 if no_bid and no_ask else None
        
        logger.info(f"[{coin}] OPEN ORDER: YES mid={yes_mid:.4f} NO mid={no_mid:.4f} (max=${OPEN_ORDER_MAX_PRICE:.2f})")
        
        # Check if both sides are cheap enough
        if yes_mid is None or no_mid is None:
            return False
        if yes_mid > OPEN_ORDER_MAX_PRICE or no_mid > OPEN_ORDER_MAX_PRICE:
            logger.info(f"[{coin}] OPEN ORDER: prices too high (YES={yes_mid:.4f} NO={no_mid:.4f}), skipping")
            return False
        
        logger.info(f"[{coin}] OPEN ORDER: BOTH SIDES <= ${OPEN_ORDER_MAX_PRICE:.2f}! Placing simultaneous orders...")
        
        # Place $1 YES and $1 NO limit orders simultaneously
        # Use limit orders at $0.15 (max price we're willing to pay)
        contracts_yes = max(1, int(OPEN_ORDER_AMOUNT / OPEN_ORDER_MAX_PRICE))
        contracts_no = max(1, int(OPEN_ORDER_AMOUNT / OPEN_ORDER_MAX_PRICE))
        
        # Place YES order
        yes_result = self.api.place_order(
            ticker=ticker,
            side='yes',
            price=OPEN_ORDER_MAX_PRICE,
            amount=OPEN_ORDER_AMOUNT,
            action='buy',
            order_type='limit'
        )
        
        # Place NO order
        no_result = self.api.place_order(
            ticker=ticker,
            side='no',
            price=OPEN_ORDER_MAX_PRICE,
            amount=OPEN_ORDER_AMOUNT,
            action='buy',
            order_type='limit'
        )
        
        yes_order_id = yes_result.get('order', {}).get('order_id') if 'order' in yes_result else None
        no_order_id = no_result.get('order', {}).get('order_id') if 'order' in no_result else None
        
        logger.info(f"[{coin}] OPEN ORDER: YES order placed: {yes_result.get('order',{})}")
        logger.info(f"[{coin}] OPEN ORDER: NO order placed: {no_result.get('order',{})}")
        
        if not yes_order_id and not no_order_id:
            logger.warning(f"[{coin}] OPEN ORDER: both orders failed to place!")
            return False
        
        # Wait for fills
        filled_yes = False
        filled_no = False
        fills_yes = 0
        fills_no = 0
        
        for i in range(OPEN_ORDER_TIMEOUT // OPEN_ORDER_POLL):
            time.sleep(OPEN_ORDER_POLL)
            
            # Check YES order
            if yes_order_id and not filled_yes:
                status = self.api._get(f"/portfolio/orders/{yes_order_id}")
                order = status.get('order', {})
                order_status = order.get('status', '')
                if order_status in ('executed', 'filled', 'complete'):
                    fills_yes = float(order.get('fill_count_fp', 0))
                    filled_yes = True
                    logger.info(f"[{coin}] OPEN ORDER: YES FILLED! {fills_yes} contracts @ ${OPEN_ORDER_MAX_PRICE:.2f}")
            
            # Check NO order
            if no_order_id and not filled_no:
                status = self.api._get(f"/portfolio/orders/{no_order_id}")
                order = status.get('order', {})
                order_status = order.get('status', '')
                if order_status in ('executed', 'filled', 'complete'):
                    fills_no = float(order.get('fill_count_fp', 0))
                    filled_no = True
                    logger.info(f"[{coin}] OPEN ORDER: NO FILLED! {fills_no} contracts @ ${OPEN_ORDER_MAX_PRICE:.2f}")
            
            if filled_yes and filled_no:
                logger.info(f"[{coin}] OPEN ORDER: BOTH SIDES FILLED! Profit locked in regardless of direction.")
                break
        
        # Cancel unfilled orders
        if yes_order_id and not filled_yes:
            self.api.cancel_order(yes_order_id)
            logger.info(f"[{coin}] OPEN ORDER: YES order cancelled (not filled)")
        if no_order_id and not filled_no:
            self.api.cancel_order(no_order_id)
            logger.info(f"[{coin}] OPEN ORDER: NO order cancelled (not filled)")
        
        # Result: both filled at <= $0.15 = success
        if filled_yes and filled_no:
            logger.info(f"[{coin}] OPEN ORDER SUCCESS: {signal_type} caught at open for ${OPEN_ORDER_AMOUNT*2:.2f} total")
            return True
        else:
            logger.info(f"[{coin}] OPEN ORDER: partial fill YES={filled_yes} NO={filled_no}, continuing with normal execution")
            return False

    def _check_12min_no_lockin(self, series_ticker: str, markets: List[Market], coin: str, trader: 'CoinTrader'):
        """
        12-MIN NO LOCK-IN ENTRY:
        At ~12 min into a 15-min window (3 min remaining), check if Coinbase price
        is at or below the window's open price (prev_close/floor_strike).
        If price <= prev_close and no existing position → enter NO at market price.

        12-min NO positions are exempt from cut-loss (hold to settlement).
        Only fires once per window (tracked in self.twelvemin_checked_windows).
        """
        # Prune closed windows: remove tickers that are no longer in markets
        current_tickers = {m.ticker for m in markets}
        stale_tickers = [
            t for t in list(self.window_open_prices[coin].keys())
            if t not in current_tickers
        ]
        for t in stale_tickers:
            del self.window_open_prices[coin][t]
            self.twelvemin_checked_windows[coin].discard(t)

        # Get Coinbase product for this coin
        product_id = COINBASE_PRODUCTS.get(coin.upper())
        if not product_id:
            return

        for market in markets:
            try:
                time_left = market.time_to_expiry_sec()
            except (AttributeError, TypeError):
                time_left = 900

            # Fire at 12-min mark: ~180s remaining (allow 150-210s window)
            if time_left > 210 or time_left < 150:
                continue

            ticker = market.ticker
            ticker_key = ticker  # unique per market

            # Skip if already checked this window
            if ticker_key in self.twelvemin_checked_windows.get(coin, set()):
                continue

            # Skip if we already have a position in this coin (allow both YES+NO per coin)
            if trader.positions:
                continue

            # Track window open prices: store floor_strike when we first see a new window
            if ticker not in self.window_open_prices[coin]:
                if market.floor_strike is not None and market.floor_strike > 0:
                    self.window_open_prices[coin][ticker] = market.floor_strike
                    logger.info(f"[12MIN] {coin} {ticker} window_open_price={market.floor_strike:.2f} (floor_strike)")
                else:
                    # No floor_strike yet — skip this market
                    continue

            prev_close = self.window_open_prices[coin].get(ticker)
            if prev_close is None:
                continue

            # Get current Coinbase price
            try:
                url = f"{COINBASE_API}/products/{product_id}/ticker"
                resp = requests.get(url, timeout=5)
                resp.raise_for_status()
                coinbase_price = float(resp.json().get("price", 0))
            except Exception as e:
                logger.debug(f"[12MIN] {coin} Coinbase price fetch failed: {e}")
                continue

            # Require significant pullback (>5%) before entering NO
            pullback_pct = (prev_close - coinbase_price) / prev_close
            if pullback_pct < 0.05:  # less than 5% pullback - crypto pumps are persistent
                logger.info(f"[{coin}] 12MIN: pullback {pullback_pct*100:.1f}% < 5%, skipping NO")
                continue

            # If price <= prev_close → enter NO
            if coinbase_price <= prev_close:
                # Mark as checked so we don't re-enter
                self.twelvemin_checked_windows[coin].add(ticker_key)

                # Place NO at market price
                # For NO contracts, price = (1 - yes_mid) since YES + NO = $1.00
                yes_mid = (market.yes_bid + market.yes_ask) / 2
                if yes_mid <= 0 or yes_mid >= 1.0:
                    yes_mid = 0.50  # Fallback
                no_price = 1 - yes_mid  # Actual NO market price

                # Ensure minimum tick size ($0.01)
                if no_price < 0.01:
                    no_price = 0.01

                # 12-MIN NO GUARD: Only enter NO when market is extended (YES expensive = NO cheap)
                # NO works like YES: only enter when market has already moved
                # Block if no_price > $0.50 (NO too expensive — paying $0.50 to win $0.50)
                if no_price > 0.50:
                    logger.info(f"[12MIN] {coin} {ticker} SKIP: NO price ${no_price:.4f} > $0.50 (NO too expensive)")
                    continue

                # Require pump context: YES must be > $0.52 (market has moved up, we're fading it)
                # If yes_mid <= $0.52, no meaningful pump to fade
                if yes_mid <= 0.52:
                    logger.info(f"[12MIN] {coin} {ticker} SKIP: YES ${yes_mid:.4f} <= $0.52 (no pump to fade)")
                    continue

                # Correlation check: block if 3+ coins showing simultaneous pullback (macro event, not reversal)
                # Count other coins where coinbase_price < prev_close (same pullback condition)
                import json as _json
                correlation_blocked = False
                try:
                    from kalshi_api import KalshiAPI
                    corr_api = KalshiAPI()
                    correlation_count = 1  # include this coin
                    for other_coin in COINS:
                        if other_coin == coin:
                            continue
                        # Check if other coin is also in pullback
                        corr_series = SERIES_TICKERS.get(other_coin, f"KX{other_coin}15M")
                        corr_markets = corr_api.get_markets(corr_series, limit=3)
                        for m in corr_markets:
                            if m.status == 'open' and m.time_to_expiry_sec() > 180:
                                try:
                                    from coinbase import get_coinbase_price
                                    other_cp = get_coinbase_price(other_coin)
                                    # Load prev_close from state
                                    other_state_file = BASE_DIR / "state" / f"{other_coin}_state.json"
                                    if other_state_file.exists():
                                        with open(other_state_file) as f:
                                            other_state = _json.load(f)
                                            other_prev_close = other_state.get('prev_close', 0)
                                            if other_prev_close > 0 and other_cp < other_prev_close:
                                                correlation_count += 1
                                except:
                                    pass
                                break
                    if correlation_count >= 3:
                        logger.warning(f"[12MIN] {coin} SKIP: {correlation_count} coins in simultaneous pullback (macro wobble, skip all)")
                        correlation_blocked = True
                except Exception as e:
                    logger.debug(f"[12MIN] {coin} correlation check failed: {e}")
                if correlation_blocked:
                    continue

                # Calculate Kelly size using NO probability (1 - yes_mid) and NO price
                from strategies import Strategy
                prob = 1 - yes_mid  # NO probability
                confidence = 55  # Conservative confidence for lock-in
                size, kelly_pct, _ = trader.strategy_engine.calculate_kelly_size(
                    Strategy.MOMENTUM, prob, confidence, no_price, cash_override=self.cash
                )

                # Apply max bet constraint
                max_dollar = MAX_BET
                if self.sizing_reduced:
                    max_dollar *= 0.5
                if no_price > 0:
                    size = math.ceil(min(size, max_dollar / no_price))

                ts_signal = TradeSignal(
                    strategy=Strategy.MOMENTUM,
                    ticker=ticker,
                    side="no",
                    direction="buy",
                    price=no_price,
                    size=int(size),
                    reason=f"12MIN_LOCKIN: {coin} NO coinbase={coinbase_price:.2f} <= prev_close={prev_close:.2f}",
                    is_candle_duration=True,  # HOLD TO SETTLEMENT
                    is_12min_no=True,  # Mark as 12-min NO for cut-loss tracking
                    confidence=confidence,
                )

                success, cost = trader._open_position(ts_signal, self.cash)
                if success:
                    self.cash -= cost
                    self.daily_trades += 1
                    logger.info(f"🔒 [{coin}] 12MIN NO LOCK-IN: {ticker} @ ${no_price:.4f} (coinbase={coinbase_price:.2f} <= prev_close={prev_close:.2f}, kelly={kelly_pct:.1%}) contracts={int(size):d}")
                else:
                    logger.warning(f"[12MIN] {coin} NO LOCK-IN order failed")

            # =============================================================
            # EXPERIMENTAL: 12-MIN YES LOCK-IN (PAPER TEST)
            # Mirror of 12-min NO — fires on pump instead of pullback
            # =============================================================
            # Reset coinbase_price for YES check (already fetched above)
            pump_pct = (coinbase_price - prev_close) / prev_close
            if pump_pct >= 0.05:
                # Pump confirmed — check YES entry conditions
                yes_mid_y = (market.yes_bid + market.yes_ask) / 2
                if yes_mid_y <= 0 or yes_mid_y >= 1.0:
                    yes_mid_y = 0.50
                no_price_y = 1 - yes_mid_y

                # EXPERIMENTAL: 12-MIN YES
                # YES price must be <= $0.50 (cheap = good entry despite pump)
                if yes_mid_y <= 0.50:
                    # NO mid must be > $0.52 (market is extended, we want to ride the pump)
                    if no_price_y > 0.52:
                        # Correlation check: block if 3+ coins in simultaneous pump
                        import json as _json
                        correlation_blocked_y = False
                        try:
                            corr_api = KalshiAPI()
                            correlation_count_y = 1
                            for other_coin in COINS:
                                if other_coin == coin:
                                    continue
                                corr_series = SERIES_TICKERS.get(other_coin, f"KX{other_coin}15M")
                                corr_markets = corr_api.get_markets(corr_series, limit=3)
                                for m in corr_markets:
                                    if m.status == 'open' and m.time_to_expiry_sec() > 180:
                                        try:
                                            other_cp = get_coinbase_price(other_coin)
                                            other_state_file = BASE_DIR / "state" / f"{other_coin}_state.json"
                                            if other_state_file.exists():
                                                with open(other_state_file) as f:
                                                    other_state = _json.load(f)
                                                    other_prev_close = other_state.get('prev_close', 0)
                                                    if other_prev_close > 0 and other_cp >= other_prev_close:
                                                        correlation_count_y += 1
                                        except:
                                            pass
                                        break
                            if correlation_count_y >= 3:
                                logger.warning(f"[12MIN-Y] {coin} SKIP: {correlation_count_y} coins in simultaneous pump (macro, skip all)")
                                correlation_blocked_y = True
                        except Exception as e:
                            logger.debug(f"[12MIN-Y] {coin} correlation check failed: {e}")

                        if not correlation_blocked_y:
                            # Calculate Kelly size
                            from strategies import Strategy
                            prob_y = yes_mid_y  # YES probability
                            confidence_y = 55
                            size_y, kelly_pct_y, _ = trader.strategy_engine.calculate_kelly_size(
                                Strategy.MOMENTUM, prob_y, confidence_y, yes_mid_y, cash_override=self.cash
                            )

                            # EXPERIMENTAL: cap at $0.50 for paper test
                            max_dollar_y = min(MAX_BET, 0.50)
                            if self.sizing_reduced:
                                max_dollar_y *= 0.5
                            if yes_mid_y > 0:
                                size_y = math.ceil(min(size_y, max_dollar_y / yes_mid_y))

                            ts_signal_y = TradeSignal(
                                strategy=Strategy.MOMENTUM,
                                ticker=ticker,
                                side="yes",
                                direction="buy",
                                price=yes_mid_y,
                                size=int(size_y),
                                reason=f"12MIN_Y_PAPER: {coin} YES coinbase={coinbase_price:.2f} >= prev_close={prev_close:.2f} pump={pump_pct*100:.1f}%",
                                is_candle_duration=True,
                                confidence=confidence_y,
                            )

                            success_y, cost_y = trader._open_position(ts_signal_y, self.cash)
                            if success_y:
                                self.cash -= cost_y
                                self.daily_trades += 1
                                logger.info(f"🌱 [12MIN-Y] {coin} EXPERIMENTAL YES LOCK-IN: {ticker} @ ${yes_mid_y:.4f} (coinbase={coinbase_price:.2f} >= prev_close={prev_close:.2f}, pump={pump_pct*100:.1f}%) contracts={int(size_y):d}")
                            else:
                                logger.warning(f"[12MIN-Y] {coin} YES LOCK-IN order failed")
                    else:
                        logger.debug(f"[12MIN-Y] {coin} {ticker} NO mid=${no_price_y:.4f} <= $0.52 — no pullback context to ride")
                else:
                    logger.debug(f"[12MIN-Y] {coin} {ticker} YES=${yes_mid_y:.4f} > $0.50 — too expensive to enter")
            else:
                logger.debug(f"[12MIN-Y] {coin} {ticker} pump={pump_pct*100:.1f}% < 5% — no entry")

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

                # Check for settled markets and update signal log (every 5 minutes)
                if not hasattr(self, "_last_settlement_check") or time.time() - self._last_settlement_check >= SETTLEMENT_CHECK_INTERVAL_SEC:
                    self._check_and_update_settled_markets()
                    self._last_settlement_check = time.time()

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
                    # ACTIVE MODE: Poll all active series every 5s
                    for series_ticker in self.our_series_tickers:
                        self._check_and_trade_series(series_ticker)
                    time.sleep(5)  # Fast polling for active markets
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

                    # If no markets found, sleep 10 seconds
                    # If markets WERE found, don't sleep - immediately go to active polling
                    if not had_markets and not self.active_series:
                        time.sleep(10)  # Fast idle polling to catch opens

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
