#!/usr/bin/env python3
# superbot.py - Superbot Main Trading Engine
# Paper trading for Kalshi 15-minute crypto binary options

import logging
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from config import (
    LOG_FILE, LOG_LEVEL, LOG_FORMAT, LOG_DATE_FORMAT,
    PAPER_MODE, PAPER_BALANCE, BALANCE_FLOOR, BALANCE_RESET_AMOUNT,
    LOOP_INTERVAL_SEC, MAX_OPEN_POSITIONS,
    KALSHI_ACCESS_KEY
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


class Superbot:
    """Main trading engine for Superbot."""
    
    def __init__(self):
        self.api = KalshiAPI(KALSHI_ACCESS_KEY)
        self.strategy_engine = StrategyEngine(PAPER_BALANCE)
        self.report = ReportGenerator()
        
        # Paper trading state
        self.cash = PAPER_BALANCE
        self.positions: Dict[str, Position] = {}  # ticker -> Position
        self.trade_history: List[Trade] = []
        
        # Shutdown flag
        self.running = True
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        logger.info("=" * 60)
        logger.info("SUPERBOT INITIALIZED - PAPER MODE")
        logger.info(f"Starting balance: ${self.cash:.2f}")
        logger.info(f"Balance floor: ${BALANCE_FLOOR:.2f}")
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
            self.strategy_engine.update_cash(self.cash)
            self.report.stats.starting_balance = BALANCE_RESET_AMOUNT
    
    def _open_position(self, signal: TradeSignal) -> bool:
        """Open a new position based on trading signal."""
        ticker = signal.ticker
        
        # Check if we already have a position in this ticker
        if ticker in self.positions:
            logger.debug(f"Position already exists for {ticker}, skipping")
            return False
        
        # Check max positions
        if len(self.positions) >= MAX_OPEN_POSITIONS:
            logger.debug(f"Max positions ({MAX_OPEN_POSITIONS}) reached, skipping")
            return False
        
        # Check if we have enough cash
        if signal.size > self.cash:
            logger.warning(f"Insufficient cash: ${self.cash:.2f} < ${signal.size:.2f}")
            return False
        
        # Deduct cost from cash
        # For YES bet: cost = price * size
        # For NO bet: cost = (1 - price) * size
        if signal.side == "yes":
            cost = signal.price * signal.size
        else:
            cost = (1 - signal.price) * signal.size
        
        self.cash -= cost
        logger.info(f"Opened {signal.strategy.value}: {signal.side} {ticker} @ ${signal.price:.4f}, size=${signal.size:.2f}, cost=${cost:.2f}, remaining cash=${self.cash:.2f}")
        
        # Record position
        position = Position(
            ticker=ticker,
            side=signal.side,
            entry_price=signal.price,
            size=signal.size,
            open_time=time.time(),
            strategy=signal.strategy,
            take_profit=signal.take_profit,
            stop_loss=signal.stop_loss
        )
        self.positions[ticker] = position
        
        return True
    
    def _close_position(self, ticker: str, reason: str, exit_price: float):
        """Close a position and record the trade."""
        if ticker not in self.positions:
            return
        
        position = self.positions[ticker]
        
        # Calculate PnL
        # For YES: profit = (exit_price - entry_price) * size / entry_price? 
        # No, simpler: YES pays $1 at expiry, 0 otherwise
        # If we bought YES at $0.40, we risk $0.40 to win $0.60
        # At expiry: if YES wins, we get $1 per unit = $1/size profit
        # Actually let's use a simpler model for paper trading
        
        # Simplified PnL model:
        # If we bought YES at price P and size S:
        # - If YES wins at expiry: PnL = S * (1 - P)  (we paid P, get $1 back)
        # - If YES loses: PnL = -S * P  (we paid P, get nothing)
        # If we bought NO (sold YES):
        # - If NO wins: PnL = S * P  (we paid 1-P, get $1 back)  
        # - If NO loses: PnL = -S * (1 - P)  (we paid 1-P, get nothing)
        
        if position.side == "yes":
            # Assume YES wins at expiry (for paper trading, we mark to market)
            # Real PnL depends on actual outcome
            pnl = position.size * (exit_price - position.entry_price)
        else:
            pnl = position.size * ((1 - exit_price) - (1 - position.entry_price))
        
        self.cash += position.size + pnl  # Return stake + PnL
        
        # Record trade
        now = datetime.utcnow()
        trade = Trade(
            ticker=ticker,
            side=position.side,
            entry_price=position.entry_price,
            exit_price=exit_price,
            size=position.size,
            pnl=pnl,
            strategy=position.strategy.value,
            open_time=datetime.fromtimestamp(position.open_time).strftime("%H:%M:%S"),
            close_time=now.strftime("%H:%M:%S"),
            exit_reason=reason
        )
        self.report.record_trade(trade)
        
        logger.info(f"Closed {ticker}: {reason}, PnL=${pnl:.2f}, cash=${self.cash:.2f}")
        
        del self.positions[ticker]
    
    def _check_existing_positions(self, markets: Dict[str, Market]):
        """Check open positions for exit conditions."""
        for ticker, position in list(self.positions.items()):
            if ticker not in markets:
                # Market not in current data, skip
                continue
            
            market = markets[ticker]
            mid_price = (market.yes_bid + market.yes_ask) / 2
            time_left = market.time_to_expiry_sec()
            
            # Check if expired
            if time_left <= 0:
                # Market expired - close at settlement price
                # For YES market, settlement is typically 0 or 1
                # Use current probability as estimate
                settlement = mid_price
                self._close_position(ticker, "expired", settlement)
                continue
            
            # Check TP/SL for DRIFT strategies
            should_exit, reason = self.strategy_engine.check_position_exit(position, mid_price)
            if should_exit:
                self._close_position(ticker, reason, mid_price)
    
    def _scan_for_signals(self, markets: List[Market]) -> List[TradeSignal]:
        """Scan markets and generate trading signals."""
        signals = []
        
        # Index markets by ticker
        market_dict = {m.ticker: m for m in markets}
        
        # First check existing positions
        self._check_existing_positions(market_dict)
        
        # Update strategy engine with current cash
        self.strategy_engine.update_cash(self.cash)
        
        # Scan for new signals
        for market in markets:
            # Skip if we already have a position
            if market.ticker in self.positions:
                continue
            
            # Skip if market is about to expire
            if market.time_to_expiry_sec() < 60:
                continue
            
            signal = self.strategy_engine.evaluate_market(market)
            if signal:
                signals.append(signal)
        
        return signals
    
    def run(self):
        """Main trading loop."""
        logger.info("Starting trading loop...")
        self.report.start_session()
        
        loop_count = 0
        while self.running:
            loop_count += 1
            try:
                # Fetch markets
                markets = self.api.get_markets()
                
                if markets:
                    # Generate signals and open positions
                    signals = self._scan_for_signals(markets)
                    
                    for signal in signals:
                        if self._open_position(signal):
                            logger.info(f"New position opened: {signal.ticker}")
                
                # Check balance floor
                self._check_balance_reset()
                
                # Status log every 10 loops
                if loop_count % 10 == 0:
                    logger.info(f"Status: cash=${self.cash:.2f}, positions={len(self.positions)}, loop={loop_count}")
                
                # Sleep until next iteration
                time.sleep(LOOP_INTERVAL_SEC)
                
            except Exception as e:
                logger.error(f"Error in trading loop: {e}", exc_info=True)
                time.sleep(LOOP_INTERVAL_SEC)
        
        # Cleanup
        self._shutdown()
    
    def _shutdown(self):
        """Clean shutdown - close all positions and save report."""
        logger.info("Shutting down superbot...")
        
        # Close all open positions at current prices
        for ticker in list(self.positions.keys()):
            logger.info(f"Closing position {ticker} on shutdown")
            self._close_position(ticker, "shutdown", 0.5)  # Estimate 0.5 as exit
        
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
