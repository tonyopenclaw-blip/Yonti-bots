# kalshi_api.py - Kalshi API wrapper for Superbot
# Uses requests directly with RSA-PSS signature auth (kalshi_py SDK models don't match API)

import logging
import requests
import time
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass

from kalshi_py.auth import KalshiAuth

from config import KALSHI_BASE_URL, SERIES_TICKERS, MARKETS_LIMIT

# Rate limiting constants
API_CALL_DELAY_SEC = 0.2
MAX_RETRIES = 3
INITIAL_BACKOFF_SEC = 1.0

logger = logging.getLogger(__name__)

# Hardcoded access key for live trading
KALSHI_ACCESS_KEY_ID = "e275fa0a-90e0-4eaa-9fb1-d25c9f8ed804"
PRIVATE_KEY_PATH = "/home/ubuntu/.openclaw/workspace/workers/superbot/kalshi_private_key.pem"


@dataclass
class Market:
    """Represents a Kalshi market."""
    ticker: str
    question: str
    yes_bid: float  # Highest bid to buy YES (dollars)
    yes_ask: float  # Lowest ask to sell YES (dollars)
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


def _cents_to_dollars(cents: int) -> float:
    """Convert cents to dollars."""
    return cents / 100.0


def _dollars_to_cents(dollars: float) -> int:
    """Convert dollars to cents."""
    return int(dollars * 100)


class KalshiAPI:
    """Wrapper for Kalshi Trade API v2 using RSA-PSS signature auth."""
    
    def __init__(self, access_key: str = ""):
        self.access_key = access_key or KALSHI_ACCESS_KEY_ID
        self.base_url = KALSHI_BASE_URL
        self._auth = None
        self._session = None
    
    @property
    def auth(self) -> KalshiAuth:
        """Lazy initialization of the Kalshi auth handler."""
        if self._auth is None:
            with open(PRIVATE_KEY_PATH) as f:
                private_key_pem = f.read()
            self._auth = KalshiAuth(self.access_key, private_key_pem)
        return self._auth
    
    @property
    def session(self) -> requests.Session:
        """Lazy initialization of requests session."""
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({
                "Content-Type": "application/json",
                "Accept": "application/json"
            })
        return self._session
    
    def _get_auth_headers(self, method: str, path: str) -> Dict[str, str]:
        """Get auth headers for a request."""
        return self.auth.get_auth_headers(method, path)
    
    def _get(self, endpoint: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Make GET request to Kalshi API with retry and backoff."""
        url = f"{self.base_url}{endpoint}"
        backoff = INITIAL_BACKOFF_SEC
        
        for attempt in range(MAX_RETRIES):
            try:
                if attempt > 0:
                    time.sleep(API_CALL_DELAY_SEC)
                
                headers = self._get_auth_headers("GET", endpoint)
                resp = self.session.get(url, params=params, headers=headers, timeout=10)
                
                if resp.status_code == 429:
                    retry_after = resp.headers.get('Retry-After', str(int(backoff)))
                    wait_time = int(retry_after) if retry_after.isdigit() else backoff
                    logger.warning(f"Rate limited (429), attempt {attempt+1}/{MAX_RETRIES}, waiting {wait_time}s")
                    time.sleep(wait_time)
                    backoff *= 2
                    continue
                
                resp.raise_for_status()
                return resp.json()
                
            except requests.RequestException as e:
                if attempt < MAX_RETRIES - 1:
                    logger.warning(f"API GET failed (attempt {attempt+1}/{MAX_RETRIES}): {e}, retrying...")
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                logger.error(f"API GET failed after {MAX_RETRIES} attempts: {e}")
                return {"error": str(e)}
        
        return {"error": "Max retries exceeded"}
    
    def _post(self, endpoint: str, data: Optional[Dict] = None) -> Dict[str, Any]:
        """Make POST request to Kalshi API with retry and backoff."""
        url = f"{self.base_url}{endpoint}"
        backoff = INITIAL_BACKOFF_SEC
        
        for attempt in range(MAX_RETRIES):
            try:
                time.sleep(API_CALL_DELAY_SEC if attempt >= 0 else 0)
                
                headers = self._get_auth_headers("POST", endpoint)
                resp = self.session.post(url, json=data, headers=headers, timeout=10)
                
                if resp.status_code == 429:
                    retry_after = resp.headers.get('Retry-After', str(int(backoff)))
                    wait_time = int(retry_after) if retry_after.isdigit() else backoff
                    logger.warning(f"Rate limited (429), attempt {attempt+1}/{MAX_RETRIES}, waiting {wait_time}s")
                    time.sleep(wait_time)
                    backoff *= 2
                    continue
                
                resp.raise_for_status()
                return resp.json()
                
            except requests.RequestException as e:
                if attempt < MAX_RETRIES - 1:
                    logger.warning(f"API POST failed (attempt {attempt+1}/{MAX_RETRIES}): {e}, retrying...")
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                logger.error(f"API POST failed after {MAX_RETRIES} attempts: {e}")
                return {"error": str(e)}
        
        return {"error": "Max retries exceeded"}
    
    def get_open_markets(self, series_ticker: str = None) -> List[Market]:
        """Fetch OPEN markets for a series using the /markets endpoint."""
        if series_ticker is None:
            series_ticker = SERIES_TICKERS['BTC']
        
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
            # API returns yes_bid_dollars as float (e.g., 0.35)
            yes_bid_raw = m.get("yes_bid_dollars", m.get("yes_bid", 0))
            if not yes_bid_raw or float(yes_bid_raw) <= 0:
                continue
            
            try:
                yes_ask_raw = m.get("yes_ask_dollars", m.get("yes_ask", 0))
                no_bid_raw = m.get("no_bid_dollars", m.get("no_bid", 0))
                no_ask_raw = m.get("no_ask_dollars", m.get("no_ask", 0))
                
                # Use title as question (API field name)
                question = m.get("title", m.get("question", ""))
                
                market = Market(
                    ticker=m.get("ticker", ""),
                    question=question,
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
        """Fetch active markets for a series."""
        return self.get_open_markets(series_ticker)
    
    def _calc_prob(self, m: Dict) -> float:
        """Calculate YES probability from bid/ask."""
        yes_ask = float(m.get("yes_ask_dollars", m.get("yes_ask", 0)))
        if yes_ask > 0:
            return yes_ask
        no_bid = float(m.get("no_bid_dollars", m.get("no_bid", 0)))
        return 1.0 - no_bid if no_bid > 0 else 0.5
    
    def get_balance(self) -> float:
        """Get account balance in dollars."""
        result = self._get("/portfolio/balance")
        if "error" in result:
            logger.warning(f"Failed to get balance: {result['error']}")
            return 0.0
        # Balance is returned in cents
        balance_cents = result.get("balance", 0)
        return float(balance_cents) / 100.0
    
    def place_order(self, ticker: str, side: str, price: float, amount: float) -> Dict[str, Any]:
        """
        Place an order on Kalshi.
        side: 'yes' or 'no'
        price: probability price (e.g., 0.35 for 35 cents)
        amount: dollar amount to risk (used to calculate contract count)
        """
        try:
            # Calculate contracts from dollar amount and price
            # price is in dollars per contract (yes_bid_dollars format)
            price_str = f"{price:.4f}"
            
            if price <= 0 or amount <= 0:
                return {"error": "Invalid price or amount"}
            
            contracts = int(amount / price)  # dollar_amount / price_per_contract
            if contracts < 1:
                contracts = 1
            
            if side == "yes":
                order_data = {
                    "action": "buy",
                    "side": "yes",
                    "ticker": ticker,
                    "type": "market",
                    "yes_price_dollars": price_str,
                    "count": contracts,
                }
            else:
                no_price = round(1.0 - price, 4)
                order_data = {
                    "action": "buy",
                    "side": "no",
                    "ticker": ticker,
                    "type": "market",
                    "no_price_dollars": f"{no_price:.4f}",
                    "count": contracts,
                }
            
            return self._post("/portfolio/orders", order_data)
            
        except Exception as e:
            logger.error(f"Failed to place order: {e}")
            return {"error": str(e)}
    
    def get_open_positions(self) -> List[Dict[str, Any]]:
        """Get open positions/orders."""
        result = self._get("/portfolio/orders", params={"status": "open"})
        if "error" in result:
            return []
        return result.get("orders", [])
    
    def get_market_by_ticker(self, ticker: str) -> Optional[Market]:
        """Fetch a specific market by ticker."""
        result = self._get(f"/markets/{ticker}")
        if "error" in result:
            logger.warning(f"Failed to fetch market {ticker}: {result['error']}")
            return None
        
        m = result.get("market", result)
        if not m:
            return None
        
        try:
            yes_bid_raw = m.get("yes_bid_dollars", m.get("yes_bid", 0))
            yes_ask_raw = m.get("yes_ask_dollars", m.get("yes_ask", 0))
            no_bid_raw = m.get("no_bid_dollars", m.get("no_bid", 0))
            no_ask_raw = m.get("no_ask_dollars", m.get("no_ask", 0))
            
            question = m.get("title", m.get("question", ""))
            
            market = Market(
                ticker=m.get("ticker", ""),
                question=question,
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
        return self._get(f"/portfolio/orders/{order_id}")
    
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

    def construct_ticker(self, series_ticker: str, dt: datetime) -> str:
        """Construct a 15-min crypto market ticker from series and datetime."""
        MONTH_ABBR = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN',
                      'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
        
        day = dt.strftime("%d")
        month_abbr = MONTH_ABBR[dt.month - 1]
        year = dt.strftime("%y")
        hour = dt.strftime("%H")
        minute = dt.strftime("%M")
        
        minute_int = dt.minute
        minute_suffix = ((minute_int // 15) + 1) * 15
        if minute_suffix >= 60:
            minute_suffix = 0
        
        ts_part = f"{day}{month_abbr}{year}{hour}{minute}"
        return f"{series_ticker}-{ts_part}-{minute_suffix:02d}"
    
    def get_market_result(self, ticker: str) -> Optional[str]:
        """Fetch a market's settlement result."""
        result = self._get(f"/markets/{ticker}")
        if "error" in result:
            return None
        
        status = result.get("status", "")
        if status == "settled":
            return result.get("result", None)
        return None
