# kalshi_api.py - Kalshi API wrapper for Superbot

import logging
import requests
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass

from config import KALSHI_BASE_URL, SERIES_TICKER, MARKETS_LIMIT, KALSHI_ACCESS_KEY

logger = logging.getLogger(__name__)


@dataclass
class Market:
    """Represents a Kalshi market."""
    ticker: str
    question: str
    yes_bid: float  # Highest bid to buy YES
    yes_ask: float  # Lowest ask to sell YES
    no_bid: float
    no_ask: float
    prob_yes: float  # Calculated probability
    close_time: str  # ISO timestamp
    status: str
    last_close_ts: Optional[int] = None
    
    def time_to_expiry_sec(self) -> int:
        """Calculate seconds until close_time."""
        try:
            close = datetime.fromisoformat(self.close_time.replace("Z", ""))
            if close.tzinfo:
                close = close.replace(tzinfo=None)
            now = datetime.utcnow()
            return max(0, int((close - now).total_seconds()))
        except:
            return 0


class KalshiAPI:
    """Wrapper for Kalshi Trade API v2."""
    
    def __init__(self, access_key: str = ""):
        self.access_key = access_key or KALSHI_ACCESS_KEY
        self.base_url = KALSHI_BASE_URL
        self.session = requests.Session()
        self.session.headers.update({
            "KALSHI-ACCESS-KEY": self.access_key,
            "Content-Type": "application/json",
            "Accept": "application/json"
        })
    
    def _get(self, endpoint: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Make GET request to Kalshi API."""
        url = f"{self.base_url}{endpoint}"
        try:
            resp = self.session.get(url, params=params, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error(f"API GET failed: {url} | Error: {e}")
            return {"error": str(e)}
    
    def _post(self, endpoint: str, data: Optional[Dict] = None) -> Dict[str, Any]:
        """Make POST request to Kalshi API."""
        url = f"{self.base_url}{endpoint}"
        try:
            resp = self.session.post(url, json=data, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error(f"API POST failed: {url} | Error: {e}")
            return {"error": str(e)}
    
    def get_markets(self, limit: int = MARKETS_LIMIT) -> List[Market]:
        """Fetch active markets for the series."""
        result = self._get("/markets", params={
            "series_ticker": SERIES_TICKER,
            "limit": limit
        })
        
        if "error" in result:
            logger.warning(f"Failed to fetch markets: {result['error']}")
            return []
        
        markets = []
        for m in result.get("markets", []):
            try:
                yes_ask_raw = m.get("yes_ask_dollars", m.get("yes_ask", 0))
                yes_bid_raw = m.get("yes_bid_dollars", m.get("yes_bid", 0))
                no_ask_raw = m.get("no_ask_dollars", m.get("no_ask", 0))
                no_bid_raw = m.get("no_bid_dollars", m.get("no_bid", 0))
                
                market = Market(
                    ticker=m.get("ticker", ""),
                    question=m.get("question", ""),
                    yes_bid=float(yes_bid_raw) if yes_bid_raw else 0.0,
                    yes_ask=float(yes_ask_raw) if yes_ask_raw else 0.0,
                    no_bid=float(no_bid_raw) if no_bid_raw else 0.0,
                    no_ask=float(no_ask_raw) if no_ask_raw else 0.0,
                    prob_yes=self._calc_prob(m),
                    close_time=m.get("close_time", ""),
                    status=m.get("status", ""),
                    last_close_ts=m.get("last_close_ts")
                )
                markets.append(market)
            except (ValueError, TypeError) as e:
                logger.warning(f"Failed to parse market: {m.get('ticker')} | {e}")
                continue
        
        logger.info(f"Fetched {len(markets)} markets")
        return markets
    
    def _calc_prob(self, m: Dict) -> float:
        """Calculate YES probability from bid/ask."""
        yes_ask = float(m.get("yes_ask", 0))
        if yes_ask > 0:
            return yes_ask
        # Fallback: use 1 - no_bid
        no_bid = float(m.get("no_bid", 0))
        return 1.0 - no_bid if no_bid > 0 else 0.5
    
    def get_balance(self) -> float:
        """Get account balance (paper mode returns simulated balance)."""
        # In live mode, this would fetch from API
        # For paper trading, we manage balance externally
        return 0.0  # Paper balance managed by superbot
    
    def place_order(self, ticker: str, side: str, price: float, amount: float) -> Dict[str, Any]:
        """
        Place an order on Kalshi.
        side: 'yes' or 'no'
        price: probability price (e.g., 0.35 for 35 cents)
        amount: dollar amount to risk
        """
        if side == "yes":
            # Buying YES - pay price * 100
            cost = price * amount
            if cost > 0:
                return self._post(f"/markets/{ticker}/orders", {
                    "type": "market",
                    "side": "yes",
                    "yes_price": price
                })
        else:
            # Buying NO - pay (1 - price) * amount
            cost = (1 - price) * amount
            if cost > 0:
                return self._post(f"/markets/{ticker}/orders", {
                    "type": "market", 
                    "side": "no",
                    "no_price": 1 - price
                })
        
        return {"error": "Invalid order parameters"}
    
    def get_open_positions(self) -> List[Dict[str, Any]]:
        """Get open positions/orders."""
        result = self._get("/orders", params={"status": "open"})
        if "error" in result:
            return []
        return result.get("orders", [])
    
    def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """Get status of a specific order."""
        return self._get(f"/orders/{order_id}")
    
    def parse_ticker(self, ticker: str) -> Dict[str, Any]:
        """
        Parse ticker format: KXBTC15M-YYMMDDHHMM-00
        Returns dict with date/time info.
        """
        parts = ticker.split("-")
        if len(parts) >= 2:
            ts_part = parts[1]
            if len(ts_part) == 10:
                return {
                    "year": int("20" + ts_part[0:2]),
                    "month": int(ts_part[2:4]),
                    "day": int(ts_part[4:6]),
                    "hour": int(ts_part[6:8]),
                    "minute": int(ts_part[8:10])
                }
        return {}
