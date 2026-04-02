# kalshi_api.py - Kalshi API wrapper for Recorder (copied from superbot)

import logging
import requests
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass

from config import KALSHI_BASE_URL, SERIES_TICKERS, MARKETS_LIMIT, KALSHI_ACCESS_KEY

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
    result: Optional[str] = None  # 'yes' or 'no' when settled
    
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
            if resp.status_code == 429:
                logger.warning(f"⚠️ Rate limited! HTTP 429 from {url}")
                return {"error": "rate_limited", "status_code": 429}
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
    
    def get_open_markets(self, series_ticker: str, limit: int = 100) -> List[Market]:
        """
        Fetch open markets for a SINGLE series_ticker using /markets endpoint.
        Kalshi only accepts ONE series_ticker per request.
        """
        result = self._get("/markets", params={
            "series_ticker": series_ticker,
            "status": "open",
            "limit": limit
        })
        
        if "error" in result:
            if result.get("status_code") == 429:
                logger.warning(f"⚠️ Rate limited on /markets endpoint!")
            else:
                logger.warning(f"Failed to fetch markets: {result['error']}")
            return []
        
        markets = []
        for m in result.get("markets", []):
            # Filter for open markets with yes_bid > 0
            yes_bid_raw = m.get("yes_bid_dollars", m.get("yes_bid", 0))
            if not yes_bid_raw or float(yes_bid_raw) <= 0:
                continue
            
            try:
                yes_ask_raw = m.get("yes_ask_dollars", m.get("yes_ask", 0))
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
        
        logger.debug(f"Fetched {len(markets)} open markets for series {series_ticker}")
        return markets
    
    def get_market_result(self, ticker: str) -> Optional[str]:
        """
        Fetch a market's settlement result.
        Returns 'yes', 'no', or None if not settled yet.
        """
        result = self._get(f"/markets/{ticker}")
        if "error" in result:
            return None
        
        # Check if market is settled
        status = result.get("status", "")
        if status == "settled":
            # Get the result field
            return result.get("result", None)
        return None
    
    def _calc_prob(self, m: Dict) -> float:
        """Calculate YES probability from bid/ask."""
        yes_ask = float(m.get("yes_ask", 0))
        if yes_ask > 0:
            return yes_ask
        no_bid = float(m.get("no_bid", 0))
        return 1.0 - no_bid if no_bid > 0 else 0.5
    
    def parse_ticker(self, ticker: str) -> Dict[str, Any]:
        """
        Parse ticker format: KX{coin}15M-DDMMMYYHHMM-MM
        Example: KXBTC15M-26APR012145-45
        """
        MONTH_MAP = {
            'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4,
            'MAY': 5, 'JUN': 6, 'JUL': 7, 'AUG': 8,
            'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12
        }
        
        parts = ticker.split("-")
        if len(parts) >= 3:
            ts_part = parts[1]
            minute_suffix = parts[2]
            
            if len(ts_part) == 11:
                day = int(ts_part[0:2])
                month_abbr = ts_part[2:5]
                year = int("20" + ts_part[5:7])
                hour = int(ts_part[7:9])
                minute = int(ts_part[9:11])
                month = MONTH_MAP.get(month_abbr, 1)
                
                return {
                    "year": year,
                    "month": month,
                    "day": day,
                    "hour": hour,
                    "minute": minute,
                    "minute_suffix": int(minute_suffix),
                    "series": parts[0]
                }
        return {}

    def extract_coin(self, ticker: str) -> str:
        """Extract coin symbol from ticker (e.g., BTC from KXBTC15M-...)."""
        parsed = self.parse_ticker(ticker)
        series = parsed.get("series", "")
        if series.startswith("KX") and "15M" in series:
            return series[2:5]  # "BTC" from "KXBTC15M"
        return "UNK"
