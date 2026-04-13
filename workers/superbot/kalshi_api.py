import time
import logging
import requests
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

@dataclass
class Market:
    ticker: str
    yes_bid: float
    yes_ask: float
    yes_bid_size: float
    yes_ask_size: float
    market_type: str
    status: str
    result: Optional[str]
    open_time: str
    close_time: str
    series_ticker: str = ""
    floor_strike: Optional[float] = None  # Reference price at candle open (from API)

    def time_to_expiry_sec(self) -> float:
        """Calculate seconds until market closes."""
        try:
            from datetime import datetime
            close = datetime.fromisoformat(self.close_time.replace('Z', '+00:00'))
            now = datetime.now(close.tzinfo) if close.tzinfo else datetime.utcnow()
            delta = close - now
            return delta.total_seconds()
        except:
            return 0.0

class KalshiAPI:
    """Wrapper using kalshi_py SDK + direct requests for custom endpoints."""
    
    
    def __init__(self, access_key: str = ""):
        self.access_key = access_key
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        # Try to use kalshi_py SDK if available
        try:
            from kalshi_py import create_client
            from kalshi_py.auth import KalshiAuth
            private_key_path = '/home/ubuntu/.openclaw/workspace/workers/superbot/kalshi_private_key.pem'
            with open(private_key_path) as f:
                private_key_data = f.read()
            # Only init SDK if we have an access key
            if access_key:
                self.sdk_client = create_client(
                    access_key_id=access_key,
                    private_key_data=private_key_data
                )
                self.auth = KalshiAuth(access_key_id=access_key, private_key_pem=private_key_data)
            else:
                self.sdk_client = None
                self.auth = KalshiAuth(access_key_id='dummy', private_key_pem=private_key_data)
        except Exception as e:
            logger.warning(f"kalshi_py SDK init failed: {e}")
            self.sdk_client = None
            self.auth = None
    
    def _get_auth_headers(self, method: str, path: str) -> Dict[str, str]:
        """Generate auth headers using a freshly-signed JWT every call."""
        # Always refresh auth first - JWT tokens expire quickly
        self._refresh_auth()
        if not self.auth:
            return {}
        
        # Get fresh headers every time - no caching ( Kalshi rejects replayed signatures)
        headers = self.auth.get_auth_headers(method, path)
        return headers

    def _refresh_auth(self):
        """Recreate the auth object to get fresh signatures."""
        try:
            from kalshi_py.auth import KalshiAuth
            private_key_path = '/home/ubuntu/.openclaw/workspace/workers/superbot/kalshi_private_key.pem'
            with open(private_key_path) as f:
                private_key_data = f.read()
            if self.access_key:
                self.auth = KalshiAuth(access_key_id=self.access_key, private_key_pem=private_key_data)
                # Clear cached headers on refresh
                KalshiAPI._auth_cached_headers = None
        except Exception as e:
            logger.warning(f"Failed to refresh auth: {e}")

    def _get(self, endpoint: str, params: Dict = None) -> Dict:
        """Make authenticated GET request with auto-retry on 401."""
        url = f"{BASE_URL}{endpoint}"
        path_without_qs = endpoint.split('?')[0]
        for attempt in range(3):
            headers = self._get_auth_headers('GET', path_without_qs)
            try:
                resp = requests.get(url, headers=headers, params=params, timeout=10)
                if resp.status_code == 401 and attempt < 2:
                    logger.warning(f"GET {url} got 401 - refreshing auth and retrying...")
                    self._refresh_auth()
                    continue
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.RequestException as e:
                if attempt == 2:
                    logger.error(f"GET {url} failed after 3 attempts: {e}")
                    return {"error": str(e)}
                continue
        return {"error": "max retries exceeded"}
    
    def _post(self, endpoint: str, data: Dict) -> Dict:
        """Make authenticated POST request with auto-retry on 401."""
        url = f"{BASE_URL}{endpoint}"
        for attempt in range(3):
            headers = self._get_auth_headers('POST', endpoint)
            headers["Content-Type"] = "application/json"
            try:
                resp = requests.post(url, headers=headers, json=data, timeout=10)
                if resp.status_code == 401 and attempt < 2:
                    logger.warning(f"POST {url} got 401 - refreshing auth and retrying...")
                    self._refresh_auth()
                    continue
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.RequestException as e:
                if attempt == 2:
                    error_detail = f"POST {url} failed after 3 attempts: {e}"
                    logger.error(error_detail)
                    return {"error": error_detail}
                continue
        return {"error": "max retries exceeded"}
    
    def _delete(self, endpoint: str) -> Dict:
        """Make authenticated DELETE request."""
        url = f"{BASE_URL}{endpoint}"
        headers = self._get_auth_headers('DELETE', endpoint)
        try:
            resp = requests.delete(url, headers=headers, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"DELETE {url} failed: {e}")
            return {"error": str(e)}
    
    def get_balance(self) -> float:
        """Get account balance."""
        result = self._get("/portfolio/balance")
        if "error" in result:
            logger.warning(f"get_balance error: {result['error']}")
            return 0.0
        try:
            return float(result.get('balance', 0)) / 100.0
        except (ValueError, TypeError):
            return 0.0
    
    def get_markets(self, series_ticker: str, limit: int = 5) -> List[Market]:
        """Get markets by series ticker."""
        result = self._get("/markets", params={"series_ticker": series_ticker, "limit": limit})
        if "error" in result:
            return []
        markets = []
        for m in result.get("markets", []):
            try:
                # Parse floor_strike from market data (set at candle open)
                floor_strike_raw = m.get("floor_strike")
                floor_strike = None
                if floor_strike_raw is not None:
                    try:
                        floor_strike = float(floor_strike_raw)
                    except (ValueError, TypeError):
                        pass
                
                markets.append(Market(
                    ticker=m.get("ticker", ""),
                    yes_bid=float(m.get("yes_bid_dollars", 0) or 0),
                    yes_ask=float(m.get("yes_ask_dollars", 0) or 0),
                    yes_bid_size=float(m.get("yes_bid_size_fp", 0) or 0) / 100,
                    yes_ask_size=float(m.get("yes_ask_size_fp", 0) or 0) / 100,
                    market_type=m.get("type", ""),
                    status=m.get("status", ""),
                    result=m.get("result"),
                    open_time=m.get("open_time", ""),
                    close_time=m.get("close_time", ""),
                    floor_strike=floor_strike
                ))
            except (ValueError, TypeError) as e:
                logger.warning(f"Error parsing market: {e}")
                continue
        return markets
    
    def get_market_by_ticker(self, ticker: str) -> Optional[Market]:
        """Get a specific market by ticker."""
        result = self._get(f"/markets/{ticker}")
        if "error" in result:
            return None
        m = result.get("market", result)
        try:
            # Parse floor_strike from market data (set at candle open)
            floor_strike_raw = m.get("floor_strike")
            floor_strike = None
            if floor_strike_raw is not None:
                try:
                    floor_strike = float(floor_strike_raw)
                except (ValueError, TypeError):
                    pass
            
            return Market(
                ticker=m.get("ticker", ""),
                yes_bid=float(m.get("yes_bid_dollars", 0) or 0),
                yes_ask=float(m.get("yes_ask_dollars", 0) or 0),
                yes_bid_size=float(m.get("yes_bid_size_fp", 0) or 0) / 100,
                yes_ask_size=float(m.get("yes_ask_size_fp", 0) or 0) / 100,
                market_type=m.get("type", ""),
                status=m.get("status", ""),
                result=m.get("result"),
                open_time=m.get("open_time", ""),
                close_time=m.get("close_time", ""),
                floor_strike=floor_strike
            )
        except:
            return None
    
    def get_market_result(self, ticker: str) -> Optional[str]:
        """Get the settlement result for a market (only available after market is settled). Returns 'yes', 'no', or None."""
        result = self._get(f"/markets/{ticker}")
        if "error" in result:
            return None
        m = result.get("market", result)
        return m.get("result")
    
    def get_open_markets(self, series_ticker: str) -> List[Market]:
        """Get only open/active markets."""
        result = self._get("/markets", params={"series_ticker": series_ticker, "status": "open", "limit": 20})
        if "error" in result:
            return []
        markets = []
        for m in result.get("markets", []):
            try:
                # Parse floor_strike from market data (set at candle open)
                floor_strike_raw = m.get("floor_strike")
                floor_strike = None
                if floor_strike_raw is not None:
                    try:
                        floor_strike = float(floor_strike_raw)
                    except (ValueError, TypeError):
                        pass
                
                markets.append(Market(
                    ticker=m.get("ticker", ""),
                    yes_bid=float(m.get("yes_bid_dollars", 0) or 0),
                    yes_ask=float(m.get("yes_ask_dollars", 0) or 0),
                    yes_bid_size=float(m.get("yes_bid_size_fp", 0) or 0) / 100,
                    yes_ask_size=float(m.get("yes_ask_size_fp", 0) or 0) / 100,
                    market_type=m.get("type", ""),
                    status=m.get("status", ""),
                    result=m.get("result"),
                    open_time=m.get("open_time", ""),
                    close_time=m.get("close_time", ""),
                    series_ticker=series_ticker,
                    floor_strike=floor_strike
                ))
            except (ValueError, TypeError):
                continue
        return markets
    
    def place_order(self, ticker: str, side: str, price: float, amount: float, action: str = "buy", order_type: str = "market") -> Dict[str, Any]:
        """
        Place an order on Kalshi.
        side: 'yes' or 'no'
        action: 'buy' or 'sell' (sell = sell existing position, expecting to buy back cheaper)
        price: probability price (e.g., 0.35 for 35 cents)
        amount: dollar amount to risk
        order_type: 'market' or 'limit' (default: market)
        """
        try:
            price_str = f"{price:.2f}"
            no_price_str = f"{1.0 - price:.2f}"
            
            if price <= 0 or amount <= 0:
                return {"error": "Invalid price or amount"}
            
            contracts = int(amount / price)
            if contracts < 1:
                contracts = 1
            
            if side == "yes":
                order_data = {
                    "action": action,  # 'buy' or 'sell'
                    "side": "yes",
                    "ticker": ticker,
                    "type": order_type,  # 'market' or 'limit'
                    "yes_price_dollars": price_str,
                    "count": contracts,
                }
            else:
                order_data = {
                    "action": action,  # 'buy' or 'sell'
                    "side": "no",
                    "ticker": ticker,
                    "type": order_type,  # 'market' or 'limit'
                    "no_price_dollars": no_price_str,
                    "count": contracts,
                }
            
            return self._post("/portfolio/orders", order_data)
        except Exception as e:
            logger.error(f"place_order error: {e}")
            return {"error": str(e)}
    
    def get_open_orders(self) -> List[Dict]:
        """Get all open/resting orders."""
        result = self._get("/portfolio/orders", params={"status": "open"})
        if "error" in result:
            return []
        return result.get("orders", [])
    
    def cancel_order(self, order_id: str) -> Dict:
        """Cancel a specific order by ID."""
        return self._delete(f"/portfolio/orders/{order_id}")
    
    def get_orderbook(self, ticker: str) -> Optional[Dict]:
        """
        Get the orderbook for a market (no auth needed for market data).
        Returns dict with 'yes_bids', 'yes_asks', 'no_bids', 'no_asks' keys.
        Each is a list of [price, size] tuples.
        
        ob_imbalance = (yes_qty - no_qty) / (yes_qty + no_qty)
        where yes_qty = sum of all YES bid sizes, no_qty = sum of all NO bid sizes
        """
        result = self._get(f"/markets/{ticker}/orderbook")
        if "error" in result:
            logger.debug(f"get_orderbook error for {ticker}: {result['error']}")
            return None
        return result
