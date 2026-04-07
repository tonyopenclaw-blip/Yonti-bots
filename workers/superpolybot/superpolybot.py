#!/usr/bin/env python3
# superpolybot.py - SuperPolybot Main Trading Engine
# Paper trading for Polymarket 5-minute binary contracts
# Uses momentum matrix (bias + RSI + price position)

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

from config import (
    LOG_FILE, LOG_LEVEL, LOG_FORMAT, LOG_DATE_FORMAT,
    PAPER_MODE, PAPER_BALANCE, BALANCE_FLOOR, BALANCE_RESET_AMOUNT,
    IDLE_POLL_INTERVAL_SEC, ACTIVE_POLL_INTERVAL_SEC, MAX_POSITIONS, MAX_BET,
    TRADING_PAIRS, COINBASE_PRODUCTS,
)
from polymarket_api import PolymarketPaperAPI, Market, SyntheticMarketGenerator
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


class PolyTrader:
    """Manages trading for Polymarket markets."""

    def __init__(
        self,
        strategy_engine: StrategyEngine,
        api: PolymarketPaperAPI,
        report: ReportGenerator,
        market_gen: SyntheticMarketGenerator = None
    ):
        self.strategy_engine = strategy_engine
        self.api = api
        self.report = report
        self.market_gen = market_gen

        self.positions: Dict[str, Position] = {}
        self.cash = 0.0

    def get_markets(self) -> List[Market]:
        """Fetch active crypto binary markets (synthetic or real)."""
        if self.market_gen:
            # Use synthetic market generator (Coinbase-based)
            markets = self.market_gen.generate_markets()
            if markets:
                logger.debug(f"Generated {len(markets)} synthetic markets")
            return markets
        else:
            # Fallback to Polymarket API
            markets = self.api.get_crypto_binaries(
                min_duration_sec=240,
                max_duration_sec=360,
                limit=20
            )
            if markets:
                logger.info(f"Found {len(markets)} active crypto binaries")
            return markets

    def check_existing_positions(self, markets: List[Market]) -> bool:
        """Check open positions for exit conditions. Returns True if changed."""
        positions_changed = False

        for condition_id, position in list(self.positions.items()):
            # Find market for this position
            market = None
            for m in markets:
                if m.id == condition_id:
                    market = m
                    break

            if market is None:
                # Market not found - check if it expired
                # In paper mode, just close it at last price
                logger.warning(f"Position {condition_id}: market not found - closing")
                self._close_position(condition_id, "expired", 0.5)
                positions_changed = True
                continue

            mid_price = market.mid_price()
            time_left = market.time_to_expiry_sec()

            # Check if expired
            if time_left <= 0:
                # Use YES price as settlement indicator
                exit_price = market.yes_price if market.resolved else mid_price
                self._close_position(condition_id, "settled", exit_price)
                positions_changed = True
                continue

            # Check exit conditions
            should_exit, reason = self.strategy_engine.check_position_exit(
                position, mid_price, time_left
            )
            if should_exit:
                self._close_position(condition_id, reason, mid_price)
                positions_changed = True

        return positions_changed

    def _close_position(self, condition_id: str, reason: str, exit_price: float):
        """Close a position and record PnL."""
        if condition_id not in self.positions:
            return

        position = self.positions[condition_id]

        # Calculate PnL
        if position.side == "yes":
            pnl = (exit_price - position.entry_price) * position.contracts
        else:
            pnl = (position.entry_price - exit_price) * position.contracts

        # Update cash
        self.cash += position.size + pnl

        # Record trade result
        self.strategy_engine.record_trade_result(position.strategy, pnl)

        # Build trade record
        open_time_str = datetime.fromtimestamp(position.open_time).strftime("%Y-%m-%d %H:%M:%S UTC")
        close_time_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

        trade = Trade(
            ticker=condition_id[:20],
            side=position.side,
            entry_price=position.entry_price,
            exit_price=exit_price,
            contracts=position.contracts,
            size=position.size,
            pnl=pnl,
            strategy=position.strategy,
            open_time=open_time_str,
            close_time=close_time_str,
            exit_reason=reason,
        )
        self.report.record_trade(trade)

        if pnl >= 0:
            logger.info(f"Closed {condition_id}: {reason}, PnL=+${pnl:.2f}")
        else:
            logger.info(f"Closed {condition_id}: {reason}, PnL=-${abs(pnl):.2f}")

        del self.positions[condition_id]

    def _open_position(self, signal: TradeSignal) -> bool:
        """Open a new position from a signal."""
        condition_id = signal.condition_id

        if condition_id in self.positions:
            return False

        if len(self.positions) >= 1:  # One position per trader
            return False

        # Check balance
        if signal.size > self.cash:
            logger.warning(f"Insufficient cash: ${self.cash:.2f} < ${signal.size:.2f}")
            return False

        # Place paper order
        result = self.api.place_order(
            condition_id=condition_id,
            side=signal.side,
            price=signal.price,
            amount=signal.size,
            market_question=signal.question,
        )

        if "error" in result:
            logger.error(f"Order failed: {result['error']}")
            return False

        # Create position
        contracts = result.get("contracts", signal.size / signal.price)
        position = Position(
            condition_id=condition_id,
            side=signal.side,
            entry_price=signal.price,
            contracts=contracts,
            size=signal.size,
            open_time=time.time(),
            strategy=signal.strategy,
            peak_price=signal.price,
        )
        self.positions[condition_id] = position

        # Deduct cost from cash
        cost = result.get("cost", signal.size)
        self.cash -= cost

        logger.info(
            f"Opened {signal.strategy}: {signal.side.upper()} {condition_id[:20]} "
            f"@ ${signal.price:.4f}, size=${signal.size:.2f}, contracts={contracts:.2f}"
        )

        return True

    def scan_for_signals(self, markets: List[Market]) -> bool:
        """Scan markets for trading signals. Returns True if trade executed."""
        # Check existing positions first
        self.check_existing_positions(markets)

        # Skip if already have position
        if self.positions:
            return False

        for market in markets:
            if market.id in self.positions:
                continue

            # Skip if not enough time left
            if market.time_to_expiry_sec() < 30:
                continue

            # Evaluate for signal
            signal = self.strategy_engine.evaluate_market(market)
            if signal:
                success = self._open_position(signal)
                if success:
                    return True

        return False

    def get_status(self) -> str:
        """Get status string."""
        if self.positions:
            pos = list(self.positions.values())[0]
            return f"POLY: {pos.strategy} {pos.side}@{pos.entry_price:.2f}"
        return "POLY: idle"


class SuperPolybot:
    """
    Main trading engine for SuperPolybot.

    Paper trading for Polymarket 5-minute crypto binaries.
    Uses momentum matrix from Superbot (bias + RSI + price position).
    """

    def __init__(self):
        self.api = PolymarketPaperAPI()

        # Synthetic market generator (since Polymarket doesn't have 5-min binaries)
        self.market_gen = SyntheticMarketGenerator(COINBASE_PRODUCTS)

        self.report = ReportGenerator(
            output_file=Path(__file__).parent / "report.json"
        )

        self.trader = PolyTrader(
            strategy_engine=StrategyEngine(PAPER_BALANCE),
            api=self.api,
            report=self.report,
            market_gen=self.market_gen
        )

        self.cash = PAPER_BALANCE
        self.running = True
        self.active_markets: bool = False

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        logger.info("=" * 60)
        logger.info("SUPERPOLYBOT INITIALIZED - Paper Trading Mode")
        logger.info(f"Trading pairs: {TRADING_PAIRS}")
        logger.info(f"Starting balance: ${self.cash:.2f}")
        logger.info(f"Max positions: {MAX_POSITIONS}")
        logger.info(f"Max bet per trade: ${MAX_BET:.2f}")
        logger.info("Strategy: Momentum Matrix (bias + RSI + price position)")
        logger.info("Market Source: Synthetic 5-min crypto binaries (Coinbase-based)")
        logger.info("=" * 60)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        logger.info(f"Received signal {signum}, shutting down...")
        self.running = False

    def _check_balance_reset(self):
        """Reset balance if below floor."""
        if self.cash < BALANCE_FLOOR:
            logger.warning(f"Balance ${self.cash:.2f} below floor ${BALANCE_FLOOR:.2f}!")
            logger.warning(f"Resetting to ${BALANCE_RESET_AMOUNT:.2f}")
            self.cash = BALANCE_RESET_AMOUNT

    def run(self):
        """Main trading loop."""
        logger.info("Starting SuperPolybot trading loop...")
        self.report.start_session()

        loop_count = 0
        last_status_log = time.time()

        while self.running:
            loop_count += 1
            try:
                # Sync balance from API
                self.cash = self.api.get_balance()
                self.trader.cash = self.cash
                self.trader.strategy_engine.update_cash(self.cash)

                # Check balance floor
                self._check_balance_reset()

                # Fetch markets
                markets = self.trader.get_markets()

                if not markets:
                    # No markets - idle polling
                    self.active_markets = False
                    logger.debug(f"Idle: No active markets (poll #{loop_count})")
                    time.sleep(IDLE_POLL_INTERVAL_SEC)
                    continue

                # We have active markets
                self.active_markets = True

                # Check and manage positions
                self.trader.check_existing_positions(markets)

                # Scan for new signals
                if len(self.trader.positions) < MAX_POSITIONS:
                    trade_executed = self.trader.scan_for_signals(markets)
                    if trade_executed:
                        logger.info(
                            f"Trade executed! Balance: ${self.cash:.2f}, "
                            f"Positions: {len(self.trader.positions)}"
                        )

                # Update open trades in report
                open_trades = []
                for condition_id, pos in self.trader.positions.items():
                    # Find current price
                    current_price = pos.entry_price
                    for m in markets:
                        if m.id == condition_id:
                            current_price = m.mid_price()
                            break

                    open_trades.append({
                        "condition_id": condition_id,
                        "side": pos.side,
                        "entry_price": pos.entry_price,
                        "current_price": current_price,
                        "contracts": pos.contracts,
                        "size": pos.size,
                        "open_time": datetime.fromtimestamp(pos.open_time).strftime("%Y-%m-%d %H:%M:%S UTC"),
                        "strategy": pos.strategy,
                    })

                self.report.update_open_trades(open_trades)
                self.report.update_session_stats(
                    self.cash,
                    len(self.trader.positions),
                    open_trades
                )

                # Status log every 30 seconds
                if time.time() - last_status_log >= 30:
                    status = self.trader.get_status()
                    logger.info(
                        f"Status: balance=${self.cash:.2f}, "
                        f"positions={len(self.trader.positions)}, "
                        f"loop={loop_count}, markets={len(markets)}"
                    )
                    last_status_log = time.time()

                # Poll interval
                time.sleep(ACTIVE_POLL_INTERVAL_SEC)

            except Exception as e:
                logger.error(f"Error in trading loop: {e}", exc_info=True)
                time.sleep(5)

        # Cleanup
        self._shutdown()

    def _shutdown(self):
        """Clean shutdown."""
        logger.info("Shutting down SuperPolybot...")

        # Close all positions
        for condition_id in list(self.trader.positions.keys()):
            self.trader._close_position(condition_id, "shutdown", 0.5)

        # Final report
        self.report.end_session(self.cash)

        logger.info("=" * 60)
        logger.info(f"FINAL BALANCE: ${self.cash:.2f}")
        logger.info(f"Total trades: {len(self.report.trades)}")
        logger.info(f"Report saved to: {self.report.output_file}")
        logger.info("=" * 60)


def main():
    """Entry point."""
    bot = SuperPolybot()
    bot.run()


if __name__ == "__main__":
    main()
