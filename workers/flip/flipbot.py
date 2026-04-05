#!/usr/bin/env python3
# flipbot.py - Simple NBA Flip Bot for Kalshi
# Simple mean reversion strategy: buy cheap, sell high, buy cheap again
#
# Strategy:
# 1. For EVERY KXNBAGAME market, when yes_bid < $0.60, BUY at market price
# 2. Place LIMIT SELL order at >= $0.85
# 3. When sell executes, immediately place LIMIT BUY at <= $0.50
# 4. BOTH SIDES of every game always have working orders
#
# Paper trading: $100 balance, $2 max per position

import logging
import signal
import sys
import time
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from config import (
    LOG_FILE, LOG_LEVEL, LOG_FORMAT, LOG_DATE_FORMAT,
    PAPER_MODE, PAPER_BALANCE,
    SPORTS_SERIES, KALSHI_ACCESS_KEY,
    STATS_REPORT_INTERVAL_SEC, DATA_DIR, POLL_INTERVAL_SEC,
    NEW_MARKET_LOOKBACK_MINUTES, NEW_MARKET_BUY_MIN, NEW_MARKET_BUY_MAX
)
from kalshi_api import KalshiAPI, SportsMarket
from flip_strategy import SimpleFlipStrategy, TradeSignal, GamePair

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


@dataclass
class Trade:
    """Records a single trade for logging."""
    timestamp: str
    ticker: str
    action: str        # 'BUY' or 'SELL'
    order_type: str     # 'MARKET' or 'LIMIT'
    price: float
    size: float
    pnl: float = 0.0
    reason: str = ""


class FlipBot:
    """Main trading engine for simple flip strategy."""
    
    def __init__(self):
        self.api = KalshiAPI(KALSHI_ACCESS_KEY)
        self.strategy = SimpleFlipStrategy(PAPER_BALANCE)
        self.running = True
        self.trade_log: List[Trade] = []
        self.last_stats_time = time.time()
        
        # Track market state for working orders
        self.working_orders: Dict[str, Dict] = {}  # ticker -> order info
        
        # New market detector: track seen markets to avoid duplicates
        self.seen_markets_file = DATA_DIR / "seen_markets.json"
        self.seen_markets: set = self._load_seen_markets()
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        logger.info("=" * 60)
        logger.info("SIMPLE FLIP BOT INITIALIZED - NBA GAME EDITION")
        logger.info("Strategy: Buy <$0.60, Sell @$0.85, Buy back <$0.50")
        logger.info("Paper mode: ON")
        logger.info(f"Starting balance: ${self.strategy.cash:.2f}")
        logger.info(f"Max position size: $2.00 per side")
        logger.info(f"Poll interval: {POLL_INTERVAL_SEC} seconds")
        logger.info("=" * 60)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        logger.info(f"Received signal {signum}, shutting down...")
        self.running = False
    
    def _save_trade_to_file(self, trade_data: dict):
        """Append a single trade to flip_trades.json immediately."""
        trade_file = DATA_DIR / "flip_trades.json"
        try:
            # Load existing trades
            existing = []
            if trade_file.exists():
                try:
                    existing = json.loads(trade_file.read_text())
                    if not isinstance(existing, list):
                        existing = []
                except:
                    existing = []
            
            # Append new trade
            existing.append(trade_data)
            
            # Write back
            with open(trade_file, 'w') as f:
                json.dump(existing, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save trade to file: {e}")
    
    def _load_seen_markets(self) -> set:
        """Load set of already-seen market tickers from file."""
        try:
            if self.seen_markets_file.exists():
                data = json.loads(self.seen_markets_file.read_text())
                if isinstance(data, dict) and "seen" in data:
                    seen = set(data["seen"])
                    logger.info(f"Loaded {len(seen)} seen markets from tracking file")
                    return seen
        except Exception as e:
            logger.warning(f"Could not load seen_markets.json: {e}")
        return set()
    
    def _save_seen_markets(self):
        """Persist seen markets set to file."""
        try:
            data = {"seen": list(self.seen_markets)}
            with open(self.seen_markets_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save seen_markets: {e}")

    def _log_trade(self, ticker: str, action: str, order_type: str, 
                   price: float, size: float, pnl: float = 0.0, reason: str = ""):
        """Log a trade to history and persist immediately."""
        # Get market title if available
        market_title = ""
        pos = self.strategy.positions.get(ticker)
        if pos:
            market_title = getattr(pos, 'market_title', '')
        
        trade = Trade(
            timestamp=datetime.utcnow().isoformat(),
            ticker=ticker,
            action=action,
            order_type=order_type,
            price=price,
            size=size,
            pnl=pnl,
            reason=reason[:80] if reason else ""
        )
        self.trade_log.append(trade)
        
        # Persist to file IMMEDIATELY
        trade_data = {
            'timestamp': trade.timestamp,
            'ticker': ticker,
            'market': market_title,
            'action': action,
            'side': getattr(pos, 'side', '') if pos else '',
            'price': price,
            'size': size,
            'pnl': pnl,
            'reason': reason[:80] if reason else '',
            'order_type': order_type,
            'game_key': getattr(pos, 'game_key', '') if pos else ''
        }
        self._save_trade_to_file(trade_data)
        
        team = ticker.split('-')[-1] if '-' in ticker else ticker
        logger.info(f"TRADE: {action} {team} {order_type} @ ${price:.4f} x ${size:.2f}" +
                   (f" | PnL: ${pnl:.2f}" if pnl != 0 else "") +
                   (f" | {reason}" if reason else ""))
    
    def _scan_markets(self) -> List[GamePair]:
        """Scan all configured game markets."""
        all_game_pairs = []
        for sport_key, series_ticker in SPORTS_SERIES.items():
            markets = self.api.get_markets(series_ticker, limit=100)
            
            # Filter for tradeable markets
            live_markets = [m for m in markets if m.is_tradeable()]
            
            # Pair markets by game
            game_pairs = self.strategy.pair_markets_by_game(live_markets)
            all_game_pairs.extend(game_pairs)
        
        return all_game_pairs
    
    def _detect_and_execute_new_markets(self) -> int:
        """
        Detect newly listed markets and buy both sides immediately.
        
        A "new" market is one where open_time is within the last NEW_MARKET_LOOKBACK_MINUTES
        and we haven't seen it before.
        
        When we find a new market with yes_bid between $0.40-$0.60, we buy BOTH sides
        of the game (the new market's team AND the paired team).
        
        Returns the number of new market trades executed.
        """
        markets = []
        for sport_key, series_ticker in SPORTS_SERIES.items():
            sport_markets = self.api.get_markets(series_ticker, limit=100)
            markets.extend(sport_markets)
        
        new_market_signals = []
        
        for market in markets:
            if not market.is_tradeable():
                continue
            
            # Skip if already seen
            if market.ticker in self.seen_markets:
                continue
            
            # Check if this is a NEW market (opened within lookback window)
            if not market.is_new_market(minutes=NEW_MARKET_LOOKBACK_MINUTES):
                continue
            
            # New market! Check if it's in the buy zone
            yes_bid = market.yes_bid if market.yes_bid > 0 else market.yes_ask
            
            if not (NEW_MARKET_BUY_MIN <= yes_bid <= NEW_MARKET_BUY_MAX):
                logger.info(f"NEW MARKET detected but OUT OF BUY ZONE: {market.ticker} @ ${yes_bid:.2f}")
                # Mark as seen so we don't keep checking
                self.seen_markets.add(market.ticker)
                continue
            
            # Found a new market in buy zone! 
            # Need to find the paired market (other team in same game)
            team_short = market.ticker.split('-')[-1]
            game_id = '-'.join(market.ticker.split('-')[1:-1])
            
            logger.info(f"🎯 NEW MARKET IN BUY ZONE: {market.ticker} @ ${yes_bid:.2f} (open_time: {market.open_time})")
            
            # Find the paired market
            paired_ticker = None
            paired_market_obj = None
            for other_market in markets:
                if other_market.ticker == market.ticker:
                    continue
                other_game_id = '-'.join(other_market.ticker.split('-')[1:-1])
                if other_game_id == game_id:
                    paired_ticker = other_market.ticker
                    paired_market_obj = other_market
                    paired_price = other_market.yes_bid if other_market.yes_bid > 0 else other_market.yes_ask
                    logger.info(f"   → PAIRED market: {other_market.ticker} @ ${paired_price:.2f}")
                    break
            
            if paired_ticker and paired_market_obj:
                # Buy BOTH sides at current prices
                size = 2.00  # $2 per side
                
                # Signal to buy this market
                new_market_signals.append({
                    'ticker': market.ticker,
                    'action': 'BUY',
                    'order_type': 'MARKET',
                    'price': yes_bid,
                    'size': size,
                    'reason': f"NEW MARKET DETECTOR: new listing at ${yes_bid:.2f}, buying both sides",
                    'market_title': market.title
                })
                
                # Signal to buy paired market at its current price
                paired_price_val = paired_market_obj.yes_bid if paired_market_obj.yes_bid > 0 else paired_market_obj.yes_ask
                
                new_market_signals.append({
                    'ticker': paired_ticker,
                    'action': 'BUY',
                    'order_type': 'MARKET',
                    'price': paired_price_val,
                    'size': size,
                    'reason': f"NEW MARKET DETECTOR: paired side of {market.ticker}",
                    'market_title': paired_market_obj.title
                })
            else:
                logger.warning(f"Could not find paired market for {market.ticker}")
                # Buy just this one if we can't find pair
                new_market_signals.append({
                    'ticker': market.ticker,
                    'action': 'BUY',
                    'order_type': 'MARKET',
                    'price': yes_bid,
                    'size': 2.00,
                    'reason': f"NEW MARKET DETECTOR: new listing (no pair found)",
                    'market_title': market.title
                })
            
            # Mark as seen
            self.seen_markets.add(market.ticker)
        
        # Execute all new market signals
        trades_executed = 0
        for sig in new_market_signals:
            # Check cash
            cost = sig['price'] * sig['size']
            if cost > self.strategy.cash:
                logger.warning(f"Insufficient cash for new market buy {sig['ticker']}: ${self.strategy.cash:.2f} < ${cost:.2f}")
                continue
            
            # Execute the trade
            success = self.strategy.execute_trade(TradeSignal(
                ticker=sig['ticker'],
                team_name=sig['ticker'].split('-')[-1],
                action=sig['action'],
                order_type=sig['order_type'],
                price=sig['price'],
                size=sig['size'],
                reason=sig['reason'],
                market_title=sig['market_title']
            ))
            
            if success:
                self._log_trade(
                    sig['ticker'],
                    sig['action'],
                    sig['order_type'],
                    sig['price'],
                    sig['size'],
                    0.0,
                    sig['reason']
                )
                trades_executed += 1
        
        # Save seen markets after processing
        if new_market_signals:
            self._save_seen_markets()
        
        return trades_executed
    
    def _close_finalized_positions(self) -> int:
        """
        Check pending positions and close any where the market has finalized.
        
        When a market finalizes:
        - pending_sell: We BOUGHT YES, waiting to sell at $0.85. If market resolved YES,
          we won (would have sold at $0.85 or higher). If resolved NO, we lost (YES went to $0).
        - pending_buyback: We SOLD YES, waiting to buy back at $0.50. If market resolved NO,
          we won (YES went to $0). If resolved YES, we lost (have to buy back at $1).
        
        Returns number of positions closed.
        """
        closed_count = 0
        
        # Build a list of tickers with pending positions
        pending_tickers = [
            ticker for ticker, pos in self.strategy.positions.items()
            if pos.state.value in ["pending_sell", "pending_buyback"]
        ]
        
        if not pending_tickers:
            return 0
        
        logger.info(f"Checking {len(pending_tickers)} pending positions for finalized markets...")
        
        for ticker in pending_tickers:
            # Fetch market status via API
            market = self.api.get_market(ticker)
            
            if not market:
                logger.warning(f"Could not fetch market for {ticker}")
                continue
            
            # Skip if not finalized
            if market.status != "finalized":
                continue
            
            # Market is finalized! Determine outcome
            # result can be "yes" (YES won) or "no" (NO won)
            result = market.result.lower() if market.result else ""
            
            pos = self.strategy.positions.get(ticker)
            if not pos:
                continue
            
            # Calculate PnL based on position type and outcome
            if pos.state.value == "pending_sell":
                # We BOUGHT YES at entry_price, waiting to sell at $0.85
                # If YES won: we win (YES worth $1, we sold at $0.85 = profit)
                # If NO won: we lose (YES worth $0, position is a total loss)
                if result == "yes":
                    # WIN: We bought at entry_price, YES went to $1, we had sell at $0.85
                    # PnL = sell_price - entry_price (we assume sell would have filled at $0.85)
                    gross_pnl = (0.85 - pos.entry_price) * pos.size
                    pnl = gross_pnl * 0.984  # 1.6% Kalshi fee on winnings
                    reason = f"MARKET FINALIZED YES @ ${0.85:.2f} sell → WIN ${pnl:.2f} (gross ${gross_pnl:.2f}, fee ${gross_pnl - pnl:.3f})"
                    logger.info(f"🏆 WIN: {ticker} pending_sell → YES won! Net PnL: ${pnl:.2f}")
                else:
                    # LOSS: YES went to $0, our position is worth $0
                    pnl = 0.0 - (pos.entry_price * pos.size)  # Lost our entry cost
                    reason = f"MARKET FINALIZED NO → LOSS ${pnl:.2f}"
                    logger.info(f"❌ LOSS: {ticker} pending_sell → NO won! PnL: ${pnl:.2f}")
                
                # Update cash: we already deducted the cost when we bought
                # For loss, cash is unchanged (we lost the position value)
                # For win, we would have sold at $0.85 (but market already closed, so credit as if sold)
                # Fee is charged on winnings, so net sell proceeds = gross * 0.984
                if result == "yes":
                    # Credit the net sell proceeds (after 1.6% fee on gross winnings)
                    sell_proceeds_gross = 0.85 * pos.size
                    sell_proceeds_net = sell_proceeds_gross * 0.984
                    self.strategy.cash += sell_proceeds_net
                    self.strategy.total_pnl += pnl
                
                # Remove the position
                del self.strategy.positions[ticker]
                closed_count += 1
                
                self._log_trade(
                    ticker,
                    'CLOSE',
                    'FINALIZED',
                    0.85 if result == "yes" else 0.0,
                    pos.size,
                    pnl,
                    reason
                )
            
            elif pos.state.value == "pending_buyback":
                # We SOLD YES (shorted), waiting to buy back at $0.50
                # If YES won: we lose (have to buy back at $1)
                # If NO won: we win (YES went to $0, we can buy back for almost nothing)
                if result == "no":
                    # WIN: YES went to $0, we can buy back at ~$0
                    # We already received money when we sold at $0.85
                    # Our profit is sell_price - buyback_price (buyback at $0 since NO won)
                    gross_pnl = 0.85 * pos.size  # We sold at $0.85, buy back at $0 = $0.85 profit
                    pnl = gross_pnl * 0.984  # 1.6% Kalshi fee on winnings
                    reason = f"MARKET FINALIZED NO → WIN ${pnl:.2f} (gross ${gross_pnl:.2f}, fee ${gross_pnl - pnl:.3f})"
                    logger.info(f"🏆 WIN: {ticker} pending_buyback → NO won! Net PnL: ${pnl:.2f}")
                    # Cash already has the sell proceeds, no additional cost for buyback since YES=$0
                    self.strategy.total_pnl += pnl
                else:
                    # LOSS: YES went to $1, we have to buy back at $1
                    # We sold at $0.85, have to buy at $1 = -$0.15 per share
                    pnl = (0.85 - 1.0) * pos.size  # -$0.15 per share
                    reason = f"MARKET FINALIZED YES → LOSS ${pnl:.2f}"
                    logger.info(f"❌ LOSS: {ticker} pending_buyback → YES won! PnL: ${pnl:.2f}")
                    # Pay the buyback cost at $1
                    buyback_cost = 1.0 * pos.size
                    self.strategy.cash -= buyback_cost
                    self.strategy.total_pnl += pnl
                
                # Remove the position
                del self.strategy.positions[ticker]
                closed_count += 1
                
                self._log_trade(
                    ticker,
                    'CLOSE',
                    'FINALIZED',
                    0.0 if result == "no" else 1.0,
                    pos.size,
                    pnl,
                    reason
                )
        
        if closed_count > 0:
            logger.info(f"Closed {closed_count} finalized positions")
        
        return closed_count
    
    def _display_status(self, game_pairs: List[GamePair]):
        """Display current market status."""
        if not game_pairs:
            logger.info("No NBA game markets found")
            return
        
        logger.info("-" * 60)
        logger.info("NBA GAME MARKETS STATUS:")
        
        for pair in game_pairs[:8]:  # Show top 8
            a_price = pair.get_team_a_price()
            b_price = pair.get_team_b_price()
            
            a_team = pair.team_a_ticker.split('-')[-1] if '-' in pair.team_a_ticker else 'A'
            b_team = pair.team_b_ticker.split('-')[-1] if '-' in pair.team_b_ticker else 'B'
            
            # Status for each side
            a_status = self._get_ticker_status(pair.team_a_ticker, a_price)
            b_status = self._get_ticker_status(pair.team_b_ticker, b_price)
            
            logger.info(f"  {a_team}: ${a_price:.2f} [{a_status}] | {b_team}: ${b_price:.2f} [{b_status}]")
        
        logger.info("-" * 60)
    
    def _get_ticker_status(self, ticker: str, yes_bid: float) -> str:
        """Get status string for a ticker."""
        pos = self.strategy.positions.get(ticker)
        
        if pos is None:
            if yes_bid < 0.60:
                return "BUY ZONE"
            return "WAIT"
        
        state = pos.state.value
        if state == "has_position":
            return f"HOLD @ ${pos.entry_price:.2f}"
        elif state == "pending_sell":
            return f"SELL @ $0.85"
        elif state == "pending_buyback":
            return f"BUYBACK @ $0.50"
        return state
    
    def _execute_signals(self, signals: List[TradeSignal]):
        """Execute a list of trade signals."""
        for signal in signals:
            pos = self.strategy.positions.get(signal.ticker)
            
            # Calculate PnL for SELL (before execute so we have the entry price)
            pnl = 0.0
            if signal.action == 'SELL' and pos:
                # PnL = (sell_price - entry_price) * size
                pnl = (signal.price - pos.entry_price) * signal.size
            
            success = self.strategy.execute_trade(signal)
            if success:
                self._log_trade(
                    signal.ticker,
                    signal.action,
                    signal.order_type,
                    signal.price,
                    signal.size,
                    pnl,
                    signal.reason
                )
    
    def _report_stats(self):
        """Report session statistics."""
        elapsed = time.time() - self.start_time
        elapsed_min = elapsed / 60
        
        trades_count = len(self.trade_log)
        buys = sum(1 for t in self.trade_log if t.action == "BUY")
        sells = sum(1 for t in self.trade_log if t.action == "SELL")
        
        total_pnl = sum(t.pnl for t in self.trade_log)
        
        # Count positions by state
        states = {}
        for ticker, pos in self.strategy.positions.items():
            state = pos.state.value
            states[state] = states.get(state, 0) + 1
        
        logger.info("=" * 50)
        logger.info("SIMPLE FLIP BOT STATS")
        logger.info(f"Runtime: {elapsed_min:.1f} minutes")
        logger.info(f"Balance: ${self.strategy.cash:.2f}")
        logger.info(f"Total positions: {len(self.strategy.positions)}")
        logger.info(f"Position states: {states}")
        logger.info(f"Total trades: {trades_count} ({buys} buys, {sells} sells)")
        logger.info(f"Session PnL: ${total_pnl:.2f}")
        logger.info("=" * 50)
        
        # Save stats
        stats_file = DATA_DIR / "flip_stats.json"
        stats_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "runtime_minutes": elapsed_min,
            "balance": self.strategy.cash,
            "total_positions": len(self.strategy.positions),
            "position_states": states,
            "total_trades": trades_count,
            "session_pnl": total_pnl,
            "mode": "simple_flip"
        }
        with open(stats_file, 'w') as f:
            json.dump(stats_data, f, indent=2)
    
    def _get_next_game_start(self, markets: List) -> Optional[datetime]:
        """Get the start time of the next game from a list of markets."""
        from datetime import datetime
        next_start = None
        for market in markets:
            try:
                close_str = market.close_time
                if close_str:
                    # close_time is when market expires (game start for game winner)
                    close_dt = datetime.fromisoformat(close_str.replace('Z', '+00:00'))
                    if next_start is None or close_dt < next_start:
                        next_start = close_dt
            except:
                continue
        return next_start

    def run(self):
        """Main trading loop."""
        logger.info(f"Starting flip bot trading loop (poll every {POLL_INTERVAL_SEC}s)...")
        self.start_time = time.time()
        
        loop_count = 0
        last_display_time = 0
        dormant_mode = False
        dormant_check_interval = 60  # Check every 60s when dormant
        
        while self.running:
            loop_count += 1
            try:
                # FIRST: Check for new markets (highest priority)
                new_trades = self._detect_and_execute_new_markets()
                if new_trades > 0:
                    logger.info(f"New market detector: executed {new_trades} trades")
                
                # Scan markets
                game_pairs = self._scan_markets()
                
                # Check and close any positions where markets have finalized
                closed_finalized = self._close_finalized_positions()
                if closed_finalized > 0:
                    logger.info(f"Closed {closed_finalized} positions from finalized markets")
                
                if not game_pairs:
                    if loop_count % 20 == 1:
                        logger.info("No NBA game markets found, waiting...")
                    dormant_mode = False  # Reset dormant when no markets
                else:
                    # Display status every 30 seconds
                    if time.time() - last_display_time >= 30:
                        self._display_status(game_pairs)
                        last_display_time = time.time()
                    
                    # Check if we should enter dormant mode
                    # If all positions are filled and no pending orders, check game timing
                    pending_orders = len(self.working_orders)
                    open_positions = len([p for p in self.strategy.positions.values() if p.has_position()])
                    
                    if pending_orders == 0 and open_positions > 0 and not dormant_mode:
                        # All initial fills done, check when next game starts
                        from datetime import datetime, timezone
                        next_game = self._get_next_game_start([m for mp in game_pairs for m in [mp.team_a_market, mp.team_b_market] if m])
                        if next_game:
                            now = datetime.now(timezone.utc)
                            if next_game.tzinfo is None:
                                next_game = next_game.replace(tzinfo=timezone.utc)
                            time_until_game = (next_game - now).total_seconds()
                            
                            if time_until_game > 1800:  # > 30 minutes
                                dormant_mode = True
                                logger.info(f"🎮 All fills done. Next game in {time_until_game/60:.1f} min. Entering DORMANT mode (poll every {dormant_check_interval}s)")
                            else:
                                logger.info(f"🎮 All fills done. Game starts in {time_until_game/60:.1f} min. Staying ACTIVE")
                    
                    # Get trade signals (only if not dormant or exiting dormant)
                    if not dormant_mode:
                        signals = self.strategy.get_signals(game_pairs)
                        if signals:
                            logger.info(f"Generated {len(signals)} trade signals")
                            self._execute_signals(signals)
                    else:
                        # In dormant mode - check if we should wake up
                        from datetime import datetime, timezone
                        next_game = self._get_next_game_start([m for mp in game_pairs for m in [mp.team_a_market, mp.team_b_market] if m])
                        if next_game:
                            now = datetime.now(timezone.utc)
                            if next_game.tzinfo is None:
                                next_game = next_game.replace(tzinfo=timezone.utc)
                            time_until_game = (next_game - now).total_seconds()
                            
                            if time_until_game <= 1800:  # Within 30 minutes
                                dormant_mode = False
                                logger.info(f"🎮 WAKING UP - Game starts in {time_until_game/60:.1f} min!")
                
                # Report stats every 5 minutes
                if time.time() - self.last_stats_time >= STATS_REPORT_INTERVAL_SEC:
                    self._report_stats()
                    self.last_stats_time = time.time()
                
                # Sleep - longer if dormant
                sleep_time = dormant_check_interval if dormant_mode else POLL_INTERVAL_SEC
                time.sleep(sleep_time)
                
            except Exception as e:
                logger.error(f"Error in trading loop: {e}", exc_info=True)
                time.sleep(POLL_INTERVAL_SEC)
        
        # Cleanup
        self._shutdown()
    
    def _shutdown(self):
        """Clean shutdown."""
        logger.info("Shutting down flip bot...")
        
        # Save trade log
        trade_log_file = DATA_DIR / "flip_trades.json"
        with open(trade_log_file, 'w') as f:
            json.dump([{
                'timestamp': t.timestamp,
                'ticker': t.ticker,
                'action': t.action,
                'order_type': t.order_type,
                'price': t.price,
                'size': t.size,
                'pnl': t.pnl,
                'reason': t.reason
            } for t in self.trade_log], f, indent=2)
        
        logger.info(f"Trade log saved to {trade_log_file}")
        
        # Final report
        total_pnl = sum(t.pnl for t in self.trade_log)
        
        logger.info("=" * 60)
        logger.info("SIMPLE FLIP BOT FINAL REPORT")
        logger.info(f"Final balance: ${self.strategy.cash:.2f}")
        logger.info(f"Total trades: {len(self.trade_log)}")
        logger.info(f"Total PnL: ${total_pnl:.2f}")
        logger.info("=" * 60)


def main():
    """Entry point."""
    bot = FlipBot()
    bot.run()


if __name__ == "__main__":
    main()
