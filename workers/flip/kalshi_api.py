# kalshi_api.py - Kalshi API wrapper for Flip Bot

import logging
import requests
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass

from config import KALSHI_BASE_URL, KALSHI_ACCESS_KEY

logger = logging.getLogger(__name__)


@dataclass
class SportsMarket:
    """Represents a sports prediction market (total, spread, etc.)."""
    ticker: str
    title: str
    yes_bid: float   # Best bid for YES
    yes_ask: float   # Best ask for YES
    no_bid: float    # Best bid for NO  
    no_ask: float    # Best ask for NO
    yes_sub_title: str
    no_sub_title: str
    close_time: str
    expected_expiration_time: str
    status: str
    open_time: str = ""  # ISO timestamp when market was listed
    result: str = ""     # Market result when finalized: "yes" or "no"
    
    @property
    def mid_price(self) -> float:
        """Mid price of YES side."""
        if self.yes_bid > 0 and self.yes_ask > 0:
            return (self.yes_bid + self.yes_ask) / 2
        elif self.yes_ask > 0:
            return self.yes_ask
        elif self.yes_bid > 0:
            return self.yes_bid
        return 0.5
    
    def time_to_expiry_sec(self) -> int:
        """Calculate seconds until expected_expiration_time."""
        try:
            exp = self.expected_expiration_time
            if not exp:
                exp = self.close_time
            dt = datetime.fromisoformat(exp.replace("Z", ""))
            if dt.tzinfo:
                dt = dt.replace(tzinfo=None)
            now = datetime.utcnow()
            return max(0, int((dt - now).total_seconds()))
        except:
            return 0
    
    def is_tradeable(self) -> bool:
        """Check if market is tradeable."""
        if self.status == "finalized":
            return False
        if self.yes_ask <= 0:
            return False
        time_left = self.time_to_expiry_sec()
        if time_left <= 0:
            return False
        return True

    def is_new_market(self, minutes: int = 5) -> bool:
        """Check if market was opened within the last N minutes."""
        if not self.open_time:
            return False
        try:
            # Parse ISO timestamp
            dt = datetime.fromisoformat(self.open_time.replace("Z", "+00:00"))
            dt = dt.replace(tzinfo=None)
            now = datetime.utcnow()
            age_seconds = (now - dt).total_seconds()
            return 0 <= age_seconds <= (minutes * 60)
        except:
            return False


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
    
    def get_markets(self, series_ticker: str = None, limit: int = 100) -> List[SportsMarket]:
        """Fetch markets for a series."""
        if not series_ticker:
            return []
        
        result = self._get("/markets", params={
            "series_ticker": series_ticker,
            "limit": limit
        })
        
        if "error" in result:
            logger.warning(f"Failed to fetch markets for {series_ticker}: {result['error']}")
            return []
        
        markets = []
        for m in result.get("markets", []):
            try:
                yes_bid = float(m.get("yes_bid_dollars", 0))
                yes_ask = float(m.get("yes_ask_dollars", 0))
                no_bid = float(m.get("no_bid_dollars", 0))
                no_ask = float(m.get("no_ask_dollars", 0))
                
                # Skip markets without prices
                if yes_ask <= 0 and yes_bid <= 0:
                    continue
                
                market = SportsMarket(
                    ticker=m.get("ticker", ""),
                    title=m.get("title", ""),
                    yes_bid=yes_bid,
                    yes_ask=yes_ask,
                    no_bid=no_bid,
                    no_ask=no_ask,
                    yes_sub_title=m.get("yes_sub_title", ""),
                    no_sub_title=m.get("no_sub_title", ""),
                    close_time=m.get("close_time", ""),
                    expected_expiration_time=m.get("expected_expiration_time", ""),
                    status=m.get("status", ""),
                    open_time=m.get("open_time", "")
                )
                markets.append(market)
            except (ValueError, TypeError) as e:
                logger.warning(f"Failed to parse market: {m.get('ticker')} | {e}")
                continue
        
        logger.info(f"Fetched {len(markets)} markets for {series_ticker}")
        return markets
    
    def get_market(self, ticker: str) -> Optional[SportsMarket]:
        """Fetch a single market by ticker."""
        result = self._get(f"/markets/{ticker}")
        
        if "error" in result:
            logger.warning(f"Failed to fetch market {ticker}: {result['error']}")
            return None
        
        m = result.get("market", {})
        try:
            yes_bid = float(m.get("yes_bid_dollars", 0))
            yes_ask = float(m.get("yes_ask_dollars", 0))
            no_bid = float(m.get("no_bid_dollars", 0))
            no_ask = float(m.get("no_ask_dollars", 0))
            
            return SportsMarket(
                ticker=m.get("ticker", ""),
                title=m.get("title", ""),
                yes_bid=yes_bid,
                yes_ask=yes_ask,
                no_bid=no_bid,
                no_ask=no_ask,
                yes_sub_title=m.get("yes_sub_title", ""),
                no_sub_title=m.get("no_sub_title", ""),
                close_time=m.get("close_time", ""),
                expected_expiration_time=m.get("expected_expiration_time", ""),
                status=m.get("status", ""),
                open_time=m.get("open_time", ""),
                result=m.get("result", "")
            )
        except (ValueError, TypeError) as e:
            logger.warning(f"Failed to parse market {ticker}: {e}")
            return None
    
    def get_live_markets_all_series(self, series_dict: Dict[str, str], 
                                    min_time_sec: int = 300,
                                    max_time_sec: int = 6*3600) -> Dict[str, List[SportsMarket]]:
        """Get live markets across multiple series that are tradeable."""
        results = {}
        for name, series_ticker in series_dict.items():
            markets = self.get_markets(series_ticker, limit=100)
            # Filter for tradeable markets within time window
            live = [m for m in markets if m.is_tradeable()]
            time_filtered = [m for m in live 
                           if min_time_sec <= m.time_to_expiry_sec() <= max_time_sec]
            if time_filtered:
                results[name] = time_filtered
                logger.info(f"{name}: {len(time_filtered)} live markets")
        return results
