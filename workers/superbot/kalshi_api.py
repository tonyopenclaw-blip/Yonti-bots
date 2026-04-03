# kalshi_api.py - Kalshi API wrapper for Superbot

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
    
    def get_open_markets(self, series_ticker: str = None) -> List[Market]:
        """
        Fetch OPEN markets for a series using the /markets endpoint with status=open.
        This is the key method Recorder uses to find tradeable markets.
        Only returns markets with yes_bid > 0 (tradeable).
        """
        if series_ticker is None:
            series_ticker = SERIES_TICKERS['BTC']
        
        # Use /markets endpoint with status=open filter (same as Recorder)
        result = self._get("/markets", params={
            "series_ticker": series_ticker,
            "status": "open",
            "limit": 10
        })
        
        if "error" in result:
            logger.warning(f"Failed to fetch markets: {result['error']}")
            return []
        
        markets = []
        for m in result.get("markets", []):
            # Filter for markets with yes_bid > 0 (tradeable)
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
        
        if markets:
            logger.debug(f"Found {len(markets)} tradeable markets for {series_ticker}")
        return markets
    
    def get_markets(self, series_ticker: str = None, limit: int = MARKETS_LIMIT) -> List[Market]:
        """
        Fetch active markets for a series using the /events endpoint.
        Falls back to get_open_markets for better filtering.
        """
        # Use the improved get_open_markets method
        return self.get_open_markets(series_ticker)
    
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
    
    def get_market_by_ticker(self, ticker: str) -> Optional[Market]:
        """
        Fetch a specific market by ticker.
        Returns Market object even if market is closed/settled.
        Used to check on positions whose markets have expired.
        """
        result = self._get(f"/markets/{ticker}")
        if "error" in result:
            logger.warning(f"Failed to fetch market {ticker}: {result['error']}")
            return None
        
        m = result.get("market", {})
        if not m:
            return None
        
        try:
            yes_bid_raw = m.get("yes_bid_dollars", m.get("yes_bid", 0))
            yes_ask_raw = m.get("yes_ask_dollars", m.get("yes_ask", 0))
            no_bid_raw = m.get("no_bid_dollars", m.get("no_bid", 0))
            no_ask_raw = m.get("no_ask_dollars", m.get("no_ask", 0))
            
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
            return market
        except (ValueError, TypeError) as e:
            logger.warning(f"Failed to parse market {ticker}: {e}")
            return None
    
    def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """Get status of a specific order."""
        return self._get(f"/orders/{order_id}")
    
    def parse_ticker(self, ticker: str) -> Dict[str, Any]:
        """
        Parse ticker format: KX{coin}15M-DDMMMYYHHMM-MM
        Example: KXBTC15M-26APR012145-45
        - series: KXBTC15M
        - DDMONYYHHMM: day=26, month=APR, year=01, hour=21, minute=45
        - MM suffix: 45 (minute marker: 00, 15, 30, or 45)
        
        Returns dict with date/time info and minute suffix.
        """
        # Month abbreviation to number mapping
        MONTH_MAP = {
            'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4,
            'MAY': 5, 'JUN': 6, 'JUL': 7, 'AUG': 8,
            'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12
        }
        
        parts = ticker.split("-")
        if len(parts) >= 3:
            # series = parts[0] e.g., "KXBTC15M"
            # ts_part = parts[1] e.g., "26APR012145"
            # minute_suffix = parts[2] e.g., "45"
            ts_part = parts[1]
            minute_suffix = parts[2]
            
            if len(ts_part) == 11:
                day = int(ts_part[0:2])
                month_abbr = ts_part[2:5]
                year = int("20" + ts_part[5:7])  # 01 -> 2001
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

    def construct_ticker(self, series_ticker: str, dt: datetime) -> str:
        """
        Construct a 15-min crypto market ticker from series and datetime.
        Format: {SERIES}-{DDMONYYHHMM}-{MM_suffix}
        Example: KXBTC15M-02APR012145-45 for Apr 2, 2026 01:45 UTC
        
        The minute_suffix is 00, 15, 30, or 45 - the minute of the 15-min interval close.
        At time 01:37 UTC, we're in the 01:45 interval, so minute_suffix=45.
        """
        MONTH_ABBR = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN',
                      'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
        
        day = dt.strftime("%d")  # 2-digit day
        month_abbr = MONTH_ABBR[dt.month - 1]
        year = dt.strftime("%y")  # 2-digit year
        hour = dt.strftime("%H")  # 2-digit hour
        minute = dt.strftime("%M")  # 2-digit minute
        
        # The minute suffix is the closing minute of the 15-min interval
        # Round up to next 15-min boundary
        minute_int = dt.minute
        minute_suffix = ((minute_int // 15) + 1) * 15
        if minute_suffix >= 60:
            minute_suffix = 0
        
        ts_part = f"{day}{month_abbr}{year}{hour}{minute}"
        return f"{series_ticker}-{ts_part}-{minute_suffix:02d}"
    
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
