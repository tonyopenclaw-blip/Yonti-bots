# flip_strategy.py - Simple NBA Flip Strategy for Kalshi
# Simple mean reversion: buy cheap, sell high, buy cheap again
#
# Strategy:
# 1. For EVERY KXNBAGAME market, when yes_bid < $0.60, BUY at market price
# 2. Place LIMIT SELL at $0.85 (take profit)
# 3. When sell executes, place LIMIT BUY at $0.50 (mean reversion buyback)
# 4. BOTH SIDES of every game always have working orders
#
# Paper trading: $100 balance, $2 max per position

import logging
import time
from dataclasses import dataclass, field
from typing import Optional, List, Dict
from enum import Enum

from kalshi_api import SportsMarket

logger = logging.getLogger(__name__)

# Strategy parameters
BUY_THRESHOLD = 0.60      # Buy when yes_bid < $0.60
SELL_THRESHOLD = 0.85     # Sell at $0.85 (take profit)
BUYBACK_THRESHOLD = 0.50   # Buy back at $0.50 (mean reversion)
MAX_POSITION_SIZE = 2.0   # $2 max per position
PAPER_BALANCE = 100.0     # Paper trading balance


class SideState(Enum):
    """State of a position for one side of a game."""
    NO_POSITION = "no_position"
    HAS_POSITION = "has_position"           # Holding, waiting to sell at $0.85
    PENDING_SELL = "pending_sell"          # Sell triggered, waiting for fill
    PENDING_BUYBACK = "pending_buyback"     # Sold, waiting to buy back at $0.50


@dataclass
class MarketPosition:
    """Position state for one side of a game market."""
    ticker: str
    team_name: str
    entry_price: float = 0.0
    size: float = 0.0
    state: SideState = SideState.NO_POSITION
    open_time: float = 0.0
    # Extended fields for reporting
    market_title: str = ""
    game_key: str = ""
    side: str = ""
    
    def has_position(self) -> bool:
        return self.size > 0 and self.state in [SideState.HAS_POSITION, SideState.PENDING_SELL]


@dataclass
class GamePair:
    """A pair of markets representing the same game (opposite sides)."""
    team_a_ticker: str
    team_b_ticker: str
    team_a_market: Optional[SportsMarket] = None
    team_b_market: Optional[SportsMarket] = None
    team_a_title: str = ""
    team_b_title: str = ""
    
    @property
    def game_key(self) -> str:
        return f"{self.team_a_ticker}|{self.team_b_ticker}"
    
    def get_team_a_price(self) -> float:
        if self.team_a_market:
            return self.team_a_market.yes_bid if self.team_a_market.yes_bid > 0 else self.team_a_market.yes_ask
        return 0.0
    
    def get_team_b_price(self) -> float:
        if self.team_b_market:
            return self.team_b_market.yes_bid if self.team_b_market.yes_bid > 0 else self.team_b_market.yes_ask
        return 0.0


@dataclass
class TradeSignal:
    """Signal to execute a trade."""
    ticker: str
    team_name: str
    action: str           # 'BUY' or 'SELL'
    order_type: str       # 'MARKET' or 'LIMIT'
    price: float          # For MARKET: the current price we bought at. For LIMIT: the limit price
    size: float
    reason: str
    game_key: str = ""
    market_title: str = ""  # Market title for reporting
    side: str = ""          # 'team_a' or 'team_b' for reporting


class SimpleFlipStrategy:
    """
    Simple NBA flip strategy - buy cheap, sell high, buy cheap again.
    
    For each market in a game:
    1. When yes_bid < $0.60: BUY at market, place limit sell at $0.85
    2. When yes_bid >= $0.85: SELL, place limit buy at $0.50
    3. When yes_bid <= $0.50 (after sell): BUY back
    
    Both sides of every game always have working orders.
    """
    
    def __init__(self, cash: float = PAPER_BALANCE):
        self.cash = cash
        self.max_position = MAX_POSITION_SIZE
        
        # Positions: ticker -> MarketPosition
        self.positions: Dict[str, MarketPosition] = {}
        
        # Track total PnL
        self.total_pnl = 0.0
        self.trade_count = 0
    
    def pair_markets_by_game(self, markets: List[SportsMarket]) -> List[GamePair]:
        """
        Group markets into game pairs.
        Game winner markets come in pairs like:
        - KXNBAGAME-26APR01INDCHI-IND
        - KXNBAGAME-26APR01INDCHI-CHI
        """
        from collections import defaultdict
        
        game_dict: Dict[str, Dict[str, SportsMarket]] = defaultdict(dict)
        
        for market in markets:
            ticker = market.ticker
            parts = ticker.split('-')
            if len(parts) >= 3:
                game_id = '-'.join(parts[1:-1])
                team = parts[-1]
                game_dict[game_id][team] = market
        
        game_pairs = []
        for game_id, team_markets in game_dict.items():
            if len(team_markets) >= 2:
                teams = list(team_markets.keys())
                team_a = teams[0]
                team_b = teams[1]
                pair = GamePair(
                    team_a_ticker=team_markets[team_a].ticker,
                    team_b_ticker=team_markets[team_b].ticker,
                    team_a_market=team_markets[team_a],
                    team_b_market=team_markets[team_b],
                    team_a_title=team_markets[team_a].title,
                    team_b_title=team_markets[team_b].title
                )
                game_pairs.append(pair)
        
        return game_pairs
    
    def get_signals(self, game_pairs: List[GamePair]) -> List[TradeSignal]:
        """
        Generate trade signals for all markets based on the simple strategy.
        
        Logic per market:
        - NO POSITION + yes_bid < $0.60 → BUY at market, set limit sell at $0.85
        - HAS POSITION + yes_bid >= $0.85 → SELL, set limit buy at $0.50
        - HAS POSITION + yes_bid <= $0.50 → BUY back at $0.50
        """
        signals = []
        
        for pair in game_pairs:
            # Process Team A
            signals.extend(self._check_market(pair, pair.team_a_ticker, pair.team_a_market, 
                                              pair.get_team_a_price(), "team_a"))
            
            # Process Team B
            signals.extend(self._check_market(pair, pair.team_b_ticker, pair.team_b_market,
                                              pair.get_team_b_price(), "team_b"))
        
        return signals
    
    def _check_market(self, pair: GamePair, ticker: str, market: SportsMarket, 
                      yes_bid: float, side: str) -> List[TradeSignal]:
        """Check a single market and return any trade signals."""
        signals = []
        
        if not market or not market.is_tradeable():
            return signals
        
        pos = self.positions.get(ticker)
        
        # Extract short team name from ticker
        team_short = ticker.split('-')[-1] if '-' in ticker else ticker
        
        # State machine for each position
        if pos is None:
            # No position - check if we should enter
            if yes_bid < BUY_THRESHOLD and self.cash >= yes_bid * self.max_position:
                market_title = pair.team_a_title if side == "team_a" else pair.team_b_title
                signals.append(TradeSignal(
                    ticker=ticker,
                    team_name=team_short,
                    action='BUY',
                    order_type='MARKET',
                    price=yes_bid,
                    size=self.max_position,
                    reason=f"yes_bid ${yes_bid:.2f} < ${BUY_THRESHOLD:.2f} → BUY",
                    game_key=pair.game_key,
                    market_title=market_title,
                    side=side
                ))
        
        elif pos.state == SideState.HAS_POSITION:
            # We have a position - check exit conditions
            if yes_bid >= SELL_THRESHOLD:
                # Take profit sell
                market_title = pair.team_a_title if side == "team_a" else pair.team_b_title
                signals.append(TradeSignal(
                    ticker=ticker,
                    team_name=team_short,
                    action='SELL',
                    order_type='LIMIT',
                    price=SELL_THRESHOLD,  # Limit sell at $0.85
                    size=pos.size,
                    reason=f"yes_bid ${yes_bid:.2f} >= ${SELL_THRESHOLD:.2f} → LIMIT SELL @ ${SELL_THRESHOLD:.2f}",
                    game_key=pair.game_key,
                    market_title=market_title,
                    side=side
                ))
        
        elif pos.state == SideState.PENDING_SELL:
            # Waiting for sell to fill - no action needed (order is working)
            pass
        
        elif pos.state == SideState.PENDING_BUYBACK:
            # Waiting to buy back at $0.50
            if yes_bid <= BUYBACK_THRESHOLD:
                market_title = pair.team_a_title if side == "team_a" else pair.team_b_title
                signals.append(TradeSignal(
                    ticker=ticker,
                    team_name=team_short,
                    action='BUY',
                    order_type='LIMIT',
                    price=BUYBACK_THRESHOLD,
                    size=pos.size,
                    reason=f"yes_bid ${yes_bid:.2f} <= ${BUYBACK_THRESHOLD:.2f} → LIMIT BUY @ ${BUYBACK_THRESHOLD:.2f}",
                    game_key=pair.game_key,
                    market_title=market_title,
                    side=side
                ))
        
        return signals
    
    def execute_trade(self, signal: TradeSignal) -> bool:
        """Execute a trade signal and update positions."""
        ticker = signal.ticker
        
        if signal.action == 'BUY':
            cost = signal.price * signal.size
            if signal.order_type == 'MARKET':
                # Market buy - new position
                if cost > self.cash:
                    logger.warning(f"Insufficient cash for market buy: ${self.cash:.2f} < ${cost:.2f}")
                    return False
                
                self.cash -= cost
                
                # Create or update position
                self.positions[ticker] = MarketPosition(
                    ticker=ticker,
                    team_name=signal.team_name,
                    entry_price=signal.price,
                    size=signal.size,
                    state=SideState.PENDING_SELL,  # Wait for sell at $0.85
                    open_time=time.time(),
                    market_title=getattr(signal, 'market_title', ''),
                    game_key=signal.game_key,
                    side=getattr(signal, 'side', '')
                )
                
                logger.info(f"BUY {signal.team_name} @ ${signal.price:.4f} x ${signal.size:.2f} = ${cost:.2f} | Placed limit sell @ ${SELL_THRESHOLD:.2f}")
                self.trade_count += 1
                
            elif signal.order_type == 'LIMIT':
                # Limit buy for buyback - close the flip and start new
                pos = self.positions.get(ticker)
                if not pos:
                    logger.warning(f"No position found for buyback on {ticker}")
                    return False
                
                # Check if we had a previous sell that we're buying back
                # The position should be in PENDING_BUYBACK state
                if pos.state != SideState.PENDING_BUYBACK:
                    logger.warning(f"Position for {ticker} not in PENDING_BUYBACK state: {pos.state}")
                    # Treat as regular buy
                    if cost > self.cash:
                        logger.warning(f"Insufficient cash for limit buy: ${self.cash:.2f} < ${cost:.2f}")
                        return False
                    self.cash -= cost
                    pos.state = SideState.HAS_POSITION
                    pos.entry_price = signal.price
                else:
                    # This is a buyback after a sell - deduct cost
                    if cost > self.cash:
                        logger.warning(f"Insufficient cash for buyback: ${self.cash:.2f} < ${cost:.2f}")
                        return False
                    self.cash -= cost
                    # Update position for new round-trip
                    pos.state = SideState.PENDING_SELL
                    pos.entry_price = signal.price
                    pos.market_title = getattr(signal, 'market_title', '')
                    pos.game_key = signal.game_key
                
                logger.info(f"LIMIT BUY {signal.team_name} @ ${signal.price:.4f} x ${signal.size:.2f} | Placed limit sell @ ${SELL_THRESHOLD:.2f}")
                self.trade_count += 1
        
        elif signal.action == 'SELL':
            pos = self.positions.get(ticker)
            if not pos:
                return False
            
            # Execute sell at limit price
            revenue = signal.price * signal.size
            pnl = revenue - (pos.entry_price * signal.size)
            self.cash += revenue
            self.total_pnl += pnl
            
            logger.info(f"SELL {signal.team_name} @ ${signal.price:.4f} x ${signal.size:.2f} = ${revenue:.2f} | PnL: ${pnl:.2f}")
            
            # Update position state - now waiting to buy back at $0.50
            # Store the sell price so we can calculate round-trip PnL later
            pos.state = SideState.PENDING_BUYBACK
            # Keep entry_price = 0 to indicate we're waiting for buyback
            # The actual entry_price for the next round will be set on buyback
            
            self.trade_count += 1
        
        return True
    
    def get_status(self) -> str:
        """Get current status string."""
        active = sum(1 for p in self.positions.values() if p.has_position())
        return f"FlipBot: ${self.cash:.2f} | {active} active positions | Trades: {self.trade_count} | PnL: ${self.total_pnl:.2f}"
    
    def get_positions_summary(self) -> Dict:
        """Get summary of all positions."""
        return {
            'cash': self.cash,
            'total_pnl': self.total_pnl,
            'trade_count': self.trade_count,
            'positions': {
                ticker: {
                    'team': pos.team_name,
                    'state': pos.state.value,
                    'entry': pos.entry_price,
                    'size': pos.size
                }
                for ticker, pos in self.positions.items()
            }
        }
