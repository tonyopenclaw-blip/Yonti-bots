#!/usr/bin/env python3
# superbot.py - Superbot Main Trading Engine
# Paper trading for Kalshi 15-minute crypto binary options
# Multi-coin: BTC, ETH, SOL, XRP, DOGE, HYPE, BNB

import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from config import (
    LOG_FILE, LOG_LEVEL, LOG_FORMAT, LOG_DATE_FORMAT,
    PAPER_MODE, PAPER_BALANCE, BALANCE_FLOOR, BALANCE_RESET_AMOUNT,
    IDLE_POLL_INTERVAL_SEC, ACTIVE_POLL_INTERVAL_SEC, MAX_OPEN_POSITIONS, MAX_BET,
    KALSHI_ACCESS_KEY, COINS, SERIES_TICKERS,
    COOLDOWN_CYCLES, DAILY_STOP_LOSS_PCT
)
from kalshi_api import KalshiAPI, Market
from strategies import StrategyEngine, Strategy, Position, TradeSignal
from report import ReportGenerator, Trade

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
        
        # Fall back to direct API call
        return self.api.get_markets(series_ticker=self.series_ticker)
    
    def _check_existing_positions(self, markets: Dict[str, Market]) -> bool:
        """Check open positions for exit conditions. Returns True if positions changed."""
        positions_changed = False
        for ticker, position in list(self.positions.items()):
            market = markets.get(ticker)
            
            # Market not in current series - check if it expired
            if market is None:
                # Try to fetch the market directly to check its status
                market = self.api.get_market_by_ticker(ticker)
                if market is None:
                    # Market not found at all - treat as expired at mid price 0.5
                    logger.warning(f"[{self.coin}] Market {ticker} not found - treating as expired")
                    self._close_position(ticker, "expired", 0.5)
                    positions_changed = True
                    continue
                
                # Check if market has expired (status=closed/settled or time_left <= 0)
                if market.status in ("closed", "settled") or market.time_to_expiry_sec() <= 0:
                    mid_price = (market.yes_bid + market.yes_ask) / 2 if market.yes_bid > 0 else 0.5
                    logger.info(f"[{self.coin}] Market {ticker} expired (status={market.status}) - closing at {mid_price:.4f}")
                    self._close_position(ticker, "expired", mid_price)
                    positions_changed = True
                    continue
                else:
                    # Market still open but not in our markets dict - skip for now
                    continue
            
            mid_price = (market.yes_bid + market.yes_ask) / 2
            time_left = market.time_to_expiry_sec()
            
            # Check if expired
            if time_left <= 0:
                settlement = mid_price
                self._close_position(ticker, "expired", settlement)
                positions_changed = True
                continue
            
            # Check TP/SL for DRIFT strategies (now includes trailing stop logic)
            should_exit, reason = self.strategy_engine.check_position_exit(position, mid_price, time_left)
            if should_exit:
                self._close_position(ticker, reason, mid_price)
                positions_changed = True
                continue
            
            # === SCALE-IN LOGIC: Add to winning positions ===
            # Check if we should scale in (add more to position)
            if position.should_scale_in(mid_price):
                scale_size = position.scale_in_size
                # Check if we have cash for scale-in
                if scale_size <= self.cash:
                    # For scale-in, we add to position size but don't create new Position
                    # We update the existing position's fields
                    if position.side == "yes":
                        cost = mid_price * scale_size
                    else:
                        cost = (1 - mid_price) * scale_size
                    
                    position.record_scale_in(mid_price, scale_size)
                    self.cash -= cost
                    logger.info(f"[{self.coin}] SCALED IN {ticker}: +${scale_size:.2f} @ ${mid_price:.4f}, new_size=${position.size:.2f}")
                else:
                    logger.debug(f"[{self.coin}] Insufficient cash for scale-in: ${self.cash:.2f} < ${scale_size:.2f}")
        
        return positions_changed
    
    def _close_position(self, ticker: str, reason: str, exit_price: float):
        """Close a position and return PnL."""
        if ticker not in self.positions:
            return 0.0, None
        
        position = self.positions[ticker]
        
        # Use avg_price for PnL calculation (accounts for scale-ins)
        calc_price = position.avg_price if position.avg_price > 0 else position.entry_price
        if position.side == "yes":
            pnl = position.size * (exit_price - calc_price)
        else:
            pnl = position.size * ((1 - exit_price) - (1 - calc_price))
        
        # Apply 1.6% Kalshi fee on positive PnL (winnings)
        gross_pnl = pnl
        if pnl > 0:
            pnl = pnl * 0.984  # Net after 1.6% fee
            logger.info(f"[{self.coin}] Closed {ticker}: {reason}, Gross PnL=${gross_pnl:.2f}, Fee=${gross_pnl - pnl:.3f}, Net PnL=${pnl:.2f}")
        else:
            logger.info(f"[{self.coin}] Closed {ticker}: {reason}, PnL=${pnl:.2f}")
        
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
        
        del self.positions[ticker]
        return pnl, position.strategy
    
    def _open_position(self, signal: TradeSignal, available_cash: float) -> tuple[bool, float]:
        """
        Open a new position based on trading signal.
        Returns (success, cost).
        """
        ticker = signal.ticker
        
        # Check if we already have a position in this ticker
        if ticker in self.positions:
            return False, 0.0
        
        # Check max positions per coin
        if len(self.positions) >= 1:  # One position per coin at a time
            return False, 0.0
        
        # Check if we have enough cash
        if signal.size > available_cash:
            logger.warning(f"[{self.coin}] Insufficient cash: ${available_cash:.2f} < ${signal.size:.2f}")
            return False, 0.0
        
        # Calculate cost
        if signal.side == "yes":
            cost = signal.price * signal.size
        else:
            cost = (1 - signal.price) * signal.size
        
        logger.info(f"[{self.coin}] Opened {signal.strategy.value}: {signal.side} {ticker} @ ${signal.price:.4f}, size=${signal.size:.2f}, cost=${cost:.2f}")
        
        # Get first cross direction for this ticker from strategy engine
        first_cross_dir = self.strategy_engine.first_cross.get_direction(ticker) or ""
        
        # Record position
        position = Position(
            ticker=ticker,
            side=signal.side,
            entry_price=signal.price,
            size=signal.size,
            open_time=time.time(),
            strategy=signal.strategy,
            take_profit=signal.take_profit,
            stop_loss=signal.stop_loss,
            first_cross_direction=first_cross_dir,
            # Trailing stop defaults (15% lock-in after 20% profit)
            trailing_stop_pct=0.15,
            trailing_stop_active=False,
            trailing_stop_trigger_pct=0.20,
            peak_price=signal.price,
            scale_in_count=0,
            max_scale_ins=2,
            scale_in_size=signal.scale_in_size,
            unrealized_pnl=0.0,
            avg_price=signal.price
        )
        self.positions[ticker] = position
        
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
            
            # Skip if market is about to expire
            if market.time_to_expiry_sec() < 60:
                continue
            
            signal = self.strategy_engine.evaluate_market(market, self.coin)
            if signal:
                # Ensure max bet per coin is respected
                signal.size = min(signal.size, MAX_BET)
                signals.append(signal)
        
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
            ticker = list(self.positions.keys())[0]
            pos = self.positions[ticker]
            return f"{self.coin}: {pos.strategy.value} {pos.side}@{pos.entry_price:.2f}"
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
        
        # Daily stop-loss tracking
        self.day_start_balance = PAPER_BALANCE  # Balance at start of day
        self.day_start_time = datetime.now().strftime("%Y-%m-%d")  # Track day
        self.trading_stopped = False  # Flag when daily stop-loss triggered
        self.stop_loss_triggered = False  # Flag to indicate stop-loss was triggered this day
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        logger.info("=" * 60)
        logger.info("SUPERBOT INITIALIZED - PAPER MODE - SMART POLLING")
        logger.info(f"Coins: {COINS}")
        logger.info(f"Tickers: {list(SERIES_TICKERS.values())}")
        logger.info(f"Starting balance: ${self.cash:.2f}")
        logger.info(f"Balance floor: ${BALANCE_FLOOR:.2f}")
        logger.info(f"Max bet per coin: ${MAX_BET:.2f}")
        logger.info(f"Idle poll: {IDLE_POLL_INTERVAL_SEC}s per series | Active poll: {ACTIVE_POLL_INTERVAL_SEC}s")
        logger.info(f"Cooldown: {COOLDOWN_CYCLES} cycles after position close")
        logger.info(f"Daily stop-loss: {DAILY_STOP_LOSS_PCT*100:.0f}% ({DAILY_STOP_LOSS_PCT*100:.0f}% of ${self.day_start_balance:.2f} = ${self.day_start_balance * DAILY_STOP_LOSS_PCT:.2f} max loss)")
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
    
    def _check_daily_stop_loss(self):
        """DISABLED - keep trading through drawdowns"""
        return False
    
    def _distribute_cash_to_traders(self):
        """Distribute available cash to each coin's strategy engine."""
        per_coin_cash = self.cash / len(COINS)
        for trader in self.coin_traders.values():
            trader.strategy_engine.update_cash(per_coin_cash)
    
    def _get_coin_from_series(self, series_ticker: str) -> Optional[str]:
        """Extract coin from series_ticker (e.g., KXBTC15M -> BTC)."""
        for coin, ticker in SERIES_TICKERS.items():
            if ticker == series_ticker:
                return coin
        return None
    
    def _check_and_trade_series(self, series_ticker: str) -> bool:
        """
        Check a single series for tradeable markets and execute trades if found.
        Returns True if any new markets were found/tradable.
        Uses the same get_open_markets() as Recorder.
        """
        coin = self._get_coin_from_series(series_ticker)
        if not coin:
            return False
        
        trader = self.coin_traders[coin]
        
        # Use get_open_markets (same as Recorder) - hits /markets?status=open
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
        
        # If we already have a position, skip new trades (we'll monitor it)
        if trader.positions:
            return True
        
        # Scan for NEW trading signals
        per_coin_cash = self.cash / len(COINS)
        
        for market in markets:
            # Skip if market is about to expire
            if market.time_to_expiry_sec() < 60:
                continue
            
            # Evaluate market for trading signal
            signal = trader.strategy_engine.evaluate_market(market, coin)
            if signal:
                # Pixel: Kill filter - drift_short entry only if YES < $0.70
                if signal.strategy.value == "drift_short" and market.yes_bid > 0.70:
                    logger.info(f"[{coin}] SKIP drift_short entry @ ${market.yes_bid:.4f} - above $0.70 threshold")
                    continue
                # Pixel: drift_buy entry only if YES < $0.45
                if signal.strategy.value == "drift_buy" and market.yes_bid > 0.45:
                    logger.info(f"[{coin}] SKIP drift_buy entry @ ${market.yes_bid:.4f} - above $0.45 threshold")
                    continue
                # Ensure max bet per coin is respected
                signal.size = min(signal.size, MAX_BET)
                
                # Try to open position
                success, cost = trader._open_position(signal, per_coin_cash)
                if success:
                    self.cash -= cost
                    logger.info(f"🚀 [{coin}] TRADE EXECUTED: {signal.strategy.value} {signal.side} {signal.ticker} @ ${signal.price:.4f}, size=${signal.size:.2f}")
                    return True
        
        return True
    
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
                    # ACTIVE MODE: First, do a QUICK scan of ALL series to discover any new active ones
                    # then poll all active series every 1 second
                    for series_ticker in self.our_series_tickers:
                        self._check_and_trade_series(series_ticker)
                    time.sleep(ACTIVE_POLL_INTERVAL_SEC)
                else:
                    # IDLE MODE: Check ONE series per cycle, cycle through all coins
                    series_ticker = self.our_series_tickers[self.series_cycle % len(self.our_series_tickers)]
                    self.series_cycle += 1
                    
                    had_markets = self._check_and_trade_series(series_ticker)
                    
                    if loop_count % 30 == 1:
                        loss = self.day_start_balance - self.cash
                        loss_pct = loss / self.day_start_balance * 100 if self.day_start_balance > 0 else 0
                        logger.info(f"😴 IDLE: checked {series_ticker} (poll #{loop_count}) | Day P&L: ${loss:.2f} ({loss_pct:.1f}%)")
                    
                    # If no markets found, sleep 10 seconds
                    # If markets WERE found, don't sleep - immediately go to active polling
                    if not had_markets and not self.active_series:
                        time.sleep(IDLE_POLL_INTERVAL_SEC)
                
                # Status log every 30 seconds
                if time.time() - last_status_log >= 30:
                    total_positions = sum(len(t.positions) for t in self.coin_traders.values())
                    status_parts = [t.get_status() for t in self.coin_traders.values()]
                    
                    loss = self.day_start_balance - self.cash
                    loss_pct = loss / self.day_start_balance * 100 if self.day_start_balance > 0 else 0
                    
                    logger.info(f"Status: cash=${self.cash:.2f}, positions={total_positions}, loop={loop_count}, active_series={list(self.active_series)}")
                    logger.info(f"Day P&L: ${loss:.2f} ({loss_pct:.1f}%) / ${self.day_start_balance * DAILY_STOP_LOSS_PCT:.2f} limit")
                    logger.info(f"Coins: {' | '.join(status_parts)}")
                    
                    # Build position details for the report (with live prices)
                    positions_details = []
                    for trader in self.coin_traders.values():
                        for ticker, pos in trader.positions.items():
                            # Fetch current price from Kalshi API
                            mkt = self.api.get_market_by_ticker(ticker)
                            if mkt and mkt.yes_bid and mkt.yes_ask:
                                cur = (mkt.yes_bid + mkt.yes_ask) / 2
                            elif mkt:
                                cur = mkt.yes_bid or mkt.yes_ask or pos.entry_price
                            else:
                                cur = pos.entry_price
                            positions_details.append({
                                "ticker": pos.ticker,
                                "side": pos.side,
                                "entry_price": pos.entry_price,
                                "size": pos.size,
                                "strategy": pos.strategy.value if hasattr(pos.strategy, 'value') else str(pos.strategy),
                                "open_time": datetime.fromtimestamp(pos.open_time).strftime("%Y-%m-%d %H:%M:%S UTC") if isinstance(pos.open_time, (int, float)) else str(pos.open_time),
                                "current_price": cur
                            })
                    
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
            for ticker in list(trader.positions.keys()):
                logger.info(f"[{coin}] Closing position {ticker} on shutdown")
                trader._close_position(ticker, "shutdown", 0.5)
        
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
