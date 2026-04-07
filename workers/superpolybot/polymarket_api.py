# polymarket_api.py - Polymarket API Wrapper
# Real API integration for Polymarket 5-minute binary crypto contracts

import datetime
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import requests

from config import MARKET_DURATION_SEC, COINBASE_API

logger = logging.getLogger(__name__)

BASE_URL = "https://clob.polymarket.com"
GAMMA_URL = "https://gamma-api.polymarket.com"


@dataclass
class PolymarketMarket:
    """Represents a Polymarket market."""
    id: str              # Market ID
    question: str        # Market question
    condition_id: str     # For order matching
    active: bool         # Is market active
    closed: bool         # Is market closed
    resolved: bool        # Is market resolved
    end_date_iso: str    # End date as ISO string
    yes_price: float     # Current YES price (0-1)
    no_price: float      # Current NO price (0-1)
    creator_fee: float   # Creator fee
    volume: float        # Trading volume
    tags: List[str]      # Market tags

    # Real Polymarket fields
    up_token_id: Optional[str] = None  # UP (YES) CLOB token ID
    down_token_id: Optional[str] = None  # DOWN (NO) CLOB token ID
    slug: Optional[str] = None  # URL slug
    asset: Optional[str] = None  # e.g. "BTC", "ETH"
    interval_min: Optional[int] = None  # 5 or 15
    market_start_ts: Optional[int] = None  # Unix timestamp of market start

    # Real mid price from CLOB (best buy + best sell) / 2
    real_mid_price: Optional[float] = None
    real_up_best_bid: Optional[float] = None  # Best UP buy price
    real_up_best_ask: Optional[float] = None  # Best UP sell price
    real_down_best_bid: Optional[float] = None
    real_down_best_ask: Optional[float] = None

    def time_to_expiry_sec(self) -> float:
        """Calculate seconds until market closes."""
        try:
            end_dt = datetime.datetime.fromisoformat(self.end_date_iso.replace('Z', '+00:00'))
            now = datetime.datetime.now(datetime.timezone.utc)
            delta = end_dt - now
            return max(0, delta.total_seconds())
        except Exception:
            return 0.0

    def mid_price(self) -> float:
        """Get mid price of YES side."""
        # Use real CLOB mid price if available
        if self.real_mid_price is not None:
            return self.real_mid_price
        return (self.yes_price + self.no_price) / 2 if self.yes_price > 0 else 0.50

    def is_tradeable(self) -> bool:
        """Check if market is tradeable (active, not closed/resolved)."""
        return self.active and not self.closed and not self.resolved and self.time_to_expiry_sec() > 0


class PolymarketPaperAPI:
    """
    Paper trading API for Polymarket.
    
    Polymarket uses:
    - Gamma API for market discovery
    - CLOB API for orderbook/pricing (we simulate for paper trading)
    
    For paper trading, we simulate fills at the current mid price.
    """

    def __init__(self, api_key: str = ""):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
        if api_key:
            self.session.headers["Authorization"] = f"Bearer {api_key}"

        # Paper trading state
        self._paper_balance = 100.00
        self._paper_positions: Dict[str, dict] = {}
        self._paper_orders: List[dict] = []
        self._paper_trades: List[dict] = []

        # Real Polymarket client
        self._real_client = RealPolymarketClient()

        logger.info("PolymarketPaperAPI initialized (paper trading mode)")

    def get_balance(self) -> float:
        """Get paper trading balance."""
        return self._paper_balance

    def get_real_markets(self, interval_min: int = 5) -> List[PolymarketMarket]:
        """
        Fetch real Polymarket 5-minute crypto markets.
        This is the main entry point for getting live data.
        """
        return self._real_client.get_active_markets(interval_min=interval_min)

    def get_markets(
        self,
        status: str = "active",
        limit: int = 50
    ) -> List[PolymarketMarket]:
        """
        Fetch markets from Polymarket Gamma API.
        Returns all active markets (legacy method for compatibility).
        """
        try:
            resp = self.session.get(
                f"{GAMMA_URL}/markets",
                params={"active": "true", "limit": str(limit)},
                timeout=15
            )
            resp.raise_for_status()
            data = resp.json()

            markets_raw = data if isinstance(data, list) else data.get("data", [])
            markets = []

            for m in markets_raw:
                try:
                    tokens = m.get("tokens", []) or []
                    if len(tokens) != 2:
                        continue

                    yes_price = float(tokens[0].get("price", 0) or 0)
                    no_price = float(tokens[1].get("price", 0) or 0)
                    if yes_price + no_price == 0:
                        continue

                    market = PolymarketMarket(
                        id=m.get("id", ""),
                        question=m.get("question", ""),
                        condition_id=m.get("conditionId", m.get("condition_id", "")),
                        active=m.get("active", False),
                        closed=m.get("closed", False),
                        resolved=m.get("closed", False),
                        end_date_iso=m.get("endDate", m.get("end_date_iso", "")),
                        yes_price=yes_price,
                        no_price=no_price,
                        creator_fee=0.0,
                        volume=float(m.get("volumeNum", m.get("volume", 0)) or 0),
                        tags=m.get("tags", []) or [],
                    )
                    markets.append(market)
                except (ValueError, TypeError) as e:
                    logger.debug(f"Error parsing market: {e}")
                    continue

            return markets
        except Exception as e:
            logger.error(f"get_markets error: {e}")
            return []

    def get_order_book(self, condition_id: str) -> Dict:
        """Get order book for a market."""
        try:
            url = f"{BASE_URL}/orderbooks"
            resp = self.session.get(url, params={"market": condition_id}, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.debug(f"get_order_book error for {condition_id}: {e}")
            return {"error": str(e)}

    def place_order(
        self,
        condition_id: str,
        side: str,
        price: float,
        amount: float,
        market_question: str = ""
    ) -> Dict:
        """
        Place a paper trading order.
        In paper mode, we immediately fill at the current mid price.
        """
        if amount <= 0 or price <= 0:
            return {"error": "Invalid order parameters"}

        contracts = amount / price

        if amount > self._paper_balance:
            return {"error": f"Insufficient balance: ${self._paper_balance:.2f} < ${amount:.2f}"}

        fill_price = price

        position = {
            "condition_id": condition_id,
            "question": market_question,
            "side": side,
            "entry_price": fill_price,
            "contracts": contracts,
            "size": amount,
            "open_time": time.time(),
            "status": "open",
        }

        cost = amount
        self._paper_balance -= cost
        self._paper_positions[condition_id] = position

        logger.info(
            f"[PAPER] Order filled: {side.upper()} {condition_id} @ ${fill_price:.4f}, "
            f"contracts={contracts:.2f}, cost=${cost:.2f}, balance=${self._paper_balance:.2f}"
        )

        return {
            "success": True,
            "order_id": f"paper_{condition_id}_{int(time.time())}",
            "filled_price": fill_price,
            "contracts": contracts,
            "cost": cost,
            "balance": self._paper_balance,
        }

    def get_positions(self) -> List[Dict]:
        """Get all open paper positions."""
        return [
            {**pos, "condition_id": cid}
            for cid, pos in self._paper_positions.items()
            if pos.get("status") == "open"
        ]

    def close_position(
        self,
        condition_id: str,
        reason: str = "manual",
        exit_price: float = None
    ) -> Dict:
        """
        Close a paper position at current price or specified exit price.
        Returns PnL calculation.
        """
        if condition_id not in self._paper_positions:
            return {"error": f"Position not found: {condition_id}"}

        pos = self._paper_positions[condition_id]

        if pos["status"] != "open":
            return {"error": f"Position already closed: {condition_id}"}

        entry_price = pos["entry_price"]
        contracts = pos["contracts"]
        side = pos["side"]
        size = pos["size"]

        if exit_price is None:
            exit_price = entry_price

        if side == "yes":
            pnl = (exit_price - entry_price) * contracts
        else:
            pnl = (entry_price - exit_price) * contracts

        self._paper_balance += size + pnl

        trade = {
            "condition_id": condition_id,
            "question": pos["question"],
            "side": side,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "contracts": contracts,
            "size": size,
            "pnl": pnl,
            "exit_reason": reason,
            "close_time": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
            "open_time": datetime.datetime.fromtimestamp(pos["open_time"]).strftime("%Y-%m-%d %H:%M:%S UTC"),
        }
        self._paper_trades.append(trade)
        pos["status"] = "closed"
        pos["pnl"] = pnl
        pos["close_time"] = trade["close_time"]

        logger.info(
            f"[PAPER] Position closed: {condition_id} | {reason} | "
            f"entry=${entry_price:.4f} exit=${exit_price:.4f} | "
            f"PnL=${pnl:.2f} | balance=${self._paper_balance:.2f}"
        )

        return {
            "success": True,
            "pnl": pnl,
            "balance": self._paper_balance,
            "trade": trade,
        }

    def get_trade_history(self) -> List[Dict]:
        """Get closed trade history."""
        return [t for t in self._paper_trades if "pnl" in t]

    def cancel_order(self, order_id: str) -> Dict:
        """Cancel a paper order (no-op since we fill immediately)."""
        return {"success": True, "message": "Paper trading - no cancellation needed"}

    def get_open_orders(self) -> List[Dict]:
        """Get open orders (empty in paper mode since we fill immediately)."""
        return []


class RealPolymarketClient:
    """
    Real Polymarket API client for 5-minute BTC/ETH binary markets.
    
    Uses deterministic URL generation based on Unix timestamps to find
    the current active market, then fetches real prices from the CLOB API.
    
    API Flow:
    1. Generate URL: https://polymarket.com/event/{asset}-updown-{interval}m-{timestamp}
    2. Query Gamma API: https://gamma-api.polymarket.com/events/slug/{slug}
    3. Get CLOB prices: https://clob.polymarket.com/price?token_id=X&side=BUY/SELL
    """

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
        })
        self._cache: Dict[str, dict] = {}
        self._cache_time: Dict[str, float] = {}
        self._cache_ttl = 30  # seconds

    def _generate_slug(self, asset: str, interval_min: int, ts: int = None) -> str:
        """
        Generate the Polymarket slug for a given asset and interval.
        
        Asset: btc, eth, sol, etc.
        Interval: 5 or 15 minutes
        Ts: Unix timestamp (if None, uses current time rounded down)
        """
        if ts is None:
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            ts = int(now_utc.timestamp())

        interval_seconds = interval_min * 60
        rounded_ts = (ts // interval_seconds) * interval_seconds
        return f"{asset}-updown-{interval_min}m-{rounded_ts}"

    def _get_cached(self, key: str) -> Optional[dict]:
        """Get cached data if still fresh."""
        if key in self._cache and key in self._cache_time:
            if time.time() - self._cache_time[key] < self._cache_ttl:
                return self._cache[key]
        return None

    def _set_cache(self, key: str, data: dict):
        """Cache data with timestamp."""
        self._cache[key] = data
        self._cache_time[key] = time.time()

    def get_market_data(self, asset: str, interval_min: int = 5) -> Optional[PolymarketMarket]:
        """
        Fetch real Polymarket data for a specific asset and interval.
        
        Returns PolymarketMarket with real CLOB prices, or None if market not found.
        
        Asset can be: btc, eth, sol
        Interval: 5 or 15
        """
        slug = self._generate_slug(asset, interval_min)
        cache_key = f"{asset}_{interval_min}_{slug}"

        # Check cache
        cached = self._get_cached(cache_key)
        if cached is not None:
            return self._dict_to_market(cached)

        # Query Gamma API for market + token IDs
        gamma_url = f"{GAMMA_URL}/events/slug/{slug}"
        try:
            resp = self.session.get(gamma_url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.debug(f"Gamma API error for {slug}: {e}")
            self._set_cache(cache_key, {"error": str(e)})
            return None

        if 'markets' not in data or len(data['markets']) == 0:
            self._set_cache(cache_key, {"error": "Market not found"})
            return None

        market_data = data['markets'][0]
        market_id = market_data.get('id', '')

        # Parse token IDs
        token_ids_raw = market_data.get('clobTokenIds', '[]')
        try:
            token_ids = json.loads(token_ids_raw) if isinstance(token_ids_raw, str) else token_ids_raw
        except (json.JSONDecodeError, TypeError):
            token_ids = []

        up_token_id = token_ids[0] if len(token_ids) > 0 else None
        down_token_id = token_ids[1] if len(token_ids) > 1 else None

        # Parse prices from Gamma API's outcomePrices (the canonical market price)
        # outcomePrices format: ["0.505", "0.495"] = [UP_price, DOWN_price]
        outcome_prices_raw = market_data.get('outcomePrices', '[]')
        try:
            outcome_prices = json.loads(outcome_prices_raw) if isinstance(outcome_prices_raw, str) else outcome_prices_raw
        except (json.JSONDecodeError, TypeError):
            outcome_prices = []

        try:
            up_mid = float(outcome_prices[0]) if len(outcome_prices) > 0 else None
            down_mid = float(outcome_prices[1]) if len(outcome_prices) > 1 else None
        except (ValueError, TypeError):
            up_mid, down_mid = None, None

        # Try CLOB API for tighter bid/ask if we have token IDs
        real_up_bid, real_up_ask = self._get_token_prices(up_token_id)
        real_down_bid, real_down_ask = self._get_token_prices(down_token_id)

        # Use Gamma price as mid, CLOB bid/ask as best prices if available
        # CLOB prices are in cents ($0.01 = 0.01) - normalize if needed
        # Prefer Gamma prices as the canonical reference price
        if up_mid is None and real_up_bid and real_up_ask:
            up_mid = (float(real_up_bid) + float(real_up_ask)) / 2
        if down_mid is None and real_down_bid and real_down_ask:
            down_mid = (float(real_down_bid) + float(real_down_ask)) / 2

        # Parse timestamp from slug
        slug_parts = slug.rsplit('-', 1)
        try:
            market_start_ts = int(slug_parts[-1])
        except ValueError:
            market_start_ts = int(time.time())

        # Get end date from Gamma API (canonical)
        end_date_raw = market_data.get('endDate', '')
        end_date_iso = end_date_raw if end_date_raw else datetime.datetime.fromtimestamp(
            market_start_ts + (interval_min * 60), tz=datetime.timezone.utc
        ).isoformat()

        # Get time window display string from question
        question = market_data.get('question', '')

        # yes_price = up price (UP = YES = price goes up from entry)
        yes_price = up_mid if up_mid else 0.5
        no_price = down_mid if down_mid else 0.5

        # Volume - use market level volume (string → float)
        try:
            volume = float(market_data.get('volume', 0) or 0)
        except (ValueError, TypeError):
            volume = 0.0

        result = {
            "id": str(market_id),
            "question": question,
            "condition_id": market_data.get('conditionId', str(market_id)),
            "active": market_data.get('active', True),
            "closed": market_data.get('closed', False),
            "resolved": market_data.get('closed', False),
            "end_date_iso": end_date_iso,
            "yes_price": yes_price,
            "no_price": no_price,
            "creator_fee": 0.0,
            "volume": volume,
            "tags": market_data.get('tags', []) or [],
            "up_token_id": up_token_id,
            "down_token_id": down_token_id,
            "slug": slug,
            "asset": asset.upper(),
            "interval_min": interval_min,
            "market_start_ts": market_start_ts,
            "real_mid_price": up_mid,
            "real_up_best_bid": real_up_bid,
            "real_up_best_ask": real_up_ask,
            "real_down_best_bid": real_down_bid,
            "real_down_best_ask": real_down_ask,
        }

        self._set_cache(cache_key, result)
        return self._dict_to_market(result)

    def _get_token_prices(self, token_id: str) -> tuple:
        """
        Fetch best BUY and SELL prices for a token from CLOB.
        Returns (best_bid, best_ask) tuple.
        """
        if not token_id:
            return None, None

        price_url = f"{BASE_URL}/price"
        best_bid, best_ask = None, None

        try:
            r = self.session.get(price_url, params={'token_id': token_id, 'side': 'BUY'}, timeout=5)
            if r.status_code == 200:
                val = r.json().get('price')
                best_bid = float(val) if val is not None else None
        except Exception:
            pass

        try:
            r = self.session.get(price_url, params={'token_id': token_id, 'side': 'SELL'}, timeout=5)
            if r.status_code == 200:
                val = r.json().get('price')
                best_ask = float(val) if val is not None else None
        except Exception:
            pass

        return best_bid, best_ask

    def _dict_to_market(self, d: dict) -> Optional[PolymarketMarket]:
        """Convert dict to PolymarketMarket, or None if error."""
        if 'error' in d:
            return None
        try:
            return PolymarketMarket(
                id=str(d.get('id', '')),
                question=d.get('question', ''),
                condition_id=d.get('condition_id', ''),
                active=d.get('active', True),
                closed=d.get('closed', False),
                resolved=d.get('resolved', False),
                end_date_iso=d.get('end_date_iso', ''),
                yes_price=float(d.get('yes_price', 0.5)),
                no_price=float(d.get('no_price', 0.5)),
                creator_fee=float(d.get('creator_fee', 0.0)),
                volume=float(d.get('volume', 0)),
                tags=d.get('tags', []) or [],
                up_token_id=d.get('up_token_id'),
                down_token_id=d.get('down_token_id'),
                slug=d.get('slug'),
                asset=d.get('asset'),
                interval_min=d.get('interval_min'),
                market_start_ts=d.get('market_start_ts'),
                real_mid_price=d.get('real_mid_price'),
                real_up_best_bid=d.get('real_up_best_bid'),
                real_up_best_ask=d.get('real_up_best_ask'),
                real_down_best_bid=d.get('real_down_best_bid'),
                real_down_best_ask=d.get('real_down_best_ask'),
            )
        except (ValueError, TypeError):
            return None

    def get_active_markets(self, interval_min: int = 5) -> List[PolymarketMarket]:
        """
        Fetch all active 5-minute crypto markets.
        
        Polymarket currently supports: BTC, ETH (and sometimes SOL)
        Returns list of PolymarketMarket objects with real CLOB prices.
        """
        assets = ["btc", "eth", "sol"]
        markets = []

        for asset in assets:
            market = self.get_market_data(asset, interval_min)
            if market and market.is_tradeable():
                markets.append(market)
            elif market:
                # Market exists but is closed/expired - still include for reference
                logger.debug(f"Market {asset}_{interval_min}m exists but not tradeable: {market.closed}, {market.time_to_expiry_sec():.0f}s left")

        return markets

    def get_market_status(self, asset: str, interval_min: int = 5) -> dict:
        """
        Get status info for a market without full PolymarketMarket object.
        Useful for quick status checks.
        """
        slug = self._generate_slug(asset, interval_min)
        market = self.get_market_data(asset, interval_min)

        if market is None:
            return {
                "asset": asset.upper(),
                "interval_min": interval_min,
                "slug": slug,
                "exists": False,
                "tradeable": False,
            }

        return {
            "asset": asset.upper(),
            "interval_min": interval_min,
            "slug": slug,
            "exists": True,
            "tradeable": market.is_tradeable(),
            "market_id": market.id,
            "question": market.question,
            "time_to_expiry_sec": market.time_to_expiry_sec(),
            "up_price_mid": market.real_mid_price,
            "up_best_bid": market.real_up_best_bid,
            "up_best_ask": market.real_up_best_ask,
            "down_best_bid": market.real_down_best_bid,
            "down_best_ask": market.real_down_best_ask,
            "yes_price": market.yes_price,
            "no_price": market.no_price,
            "volume": market.volume,
        }


# Alias for compatibility with Superbot interface
Market = PolymarketMarket


# Backwards compatibility - keep SyntheticMarketGenerator name
class SyntheticMarketGenerator:
    """
    DEPRECATED: This class is kept for backwards compatibility.
    All real data now comes from RealPolymarketClient.
    
    This class now delegates to RealPolymarketClient internally.
    """

    def __init__(self, products: Dict[str, str] = None):
        self._real_client = RealPolymarketClient()
        self.products = products or {"BTC": "BTC-USD", "ETH": "ETH-USD"}

    def get_current_prices(self) -> Dict[str, float]:
        """Get current real Polymarket prices."""
        prices = {}
        for market in self._real_client.get_active_markets(interval_min=5):
            if market.asset:
                prices[market.asset] = market.real_mid_price or market.yes_price
        return prices

    def generate_markets(self) -> List[PolymarketMarket]:
        """Get real Polymarket 5-minute crypto markets."""
        return self._real_client.get_active_markets(interval_min=5)

    def reset_market(self):
        """Clear cache to force fresh fetch."""
        self._real_client._cache.clear()
        self._real_client._cache_time.clear()
