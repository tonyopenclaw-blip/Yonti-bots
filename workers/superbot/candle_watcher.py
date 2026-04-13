#!/usr/bin/env python3
"""
candle_watcher.py - Persistent 24/7 Coinbase candle watcher for Kalshi signals.
Watches 15-min candles for 8 coins and fires signals when candles complete.
"""

import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import requests

from kalshi_api import KalshiAPI
from config import KALSHI_ACCESS_KEY, COINBASE_PRODUCTS, SERIES_TICKERS

# =============================================================================
# CONFIG
# =============================================================================
BASE_DIR = Path(__file__).parent
SIGNALS_DIR = BASE_DIR / "candle_signals"
LOG_FILE = BASE_DIR / "candle_watcher.log"
SIGNAL_LOG_FILE = BASE_DIR / "signal_log.json"

# Ensure candle_signals directory exists
SIGNALS_DIR.mkdir(exist_ok=True)

def get_signal_file(coin: str) -> Path:
    """Return the per-coin signal file path."""
    return SIGNALS_DIR / f"{coin}.json"

def get_macro_ride_file(coin: str) -> Path:
    """Return the per-coin MACRO_RIDE signal file path."""
    return SIGNALS_DIR / f"{coin}_macro_ride.json"

COINBASE_API = "https://api.exchange.coinbase.com"
COINBASE_PRODUCTS = {
    "BTC": "BTC-USD",
    "ETH": "ETH-USD",
    "SOL": "SOL-USD",
    "BNB": "BNB-USD",
    "DOGE": "DOGE-USD",
    "XRP": "XRP-USD",
    "HYPE": "HYPE-USD",
    "ADA": "ADA-USD",
}

DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1486066262122430684/mLKWVlGJRyADWEnpDgx3n4QcI1B-JhAnDLyBHKwsK-BSmeo5lal5MYrrY_QiuOBqiNLy"

# Signal thresholds
BUY_YES_THRESHOLD = 0.90  # >90% of candle time above prev close → BUY YES (conf=97)
BUY_NO_THRESHOLD = 0.30  # <30% above prev_close = >70% below → bearish confirmation (lowered from 10% to catch more valid signals)
# EXPERIMENTAL: CANDLE_NO enabled with YES > $0.52 pump filter (Nerd analysis 2026-04-12)

# Macro Correlation Detector params
MACRO_WINDOW_SEC = 30      # Cluster window: 3+ coins same direction within 30s
MACRO_MIN_CLUSTER = 5     # Minimum coins to trigger macro fade (raised from 3 — 3-4 coin clusters 0W/4L vs 7-8 coin clusters 9W/0L)

# Regime filter: skip NO signals if 3 consecutive candles had >60% YES ratio
REGIME_WINDOW = 3          # Rolling window of last 3 candles
REGIME_YES_THRESHOLD = 0.60  # >60% YES ratio per candle to count as bullish regime

# =============================================================================
# LOGGING
# =============================================================================
def setup_logging():
    LOG_FILE.parent.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(LOG_FILE),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger(__name__)

logger = setup_logging()


# =============================================================================
# CANDLE TRACKER
# =============================================================================
def _load_signal_log() -> list:
    """Load existing signal log or empty list."""
    if SIGNAL_LOG_FILE.exists():
        try:
            with open(SIGNAL_LOG_FILE, "r") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except (json.JSONDecodeError, IOError):
            return []
    return []


def _append_signal_log(entry: dict):
    """Append a signal entry to the signal log file."""
    log = _load_signal_log()
    log.append(entry)
    try:
        with open(SIGNAL_LOG_FILE, "w") as f:
            json.dump(log, f, indent=2)
    except IOError as e:
        logger.warning(f"Failed to write signal log: {e}")



def _get_market_mid_at_signal(coin: str) -> Optional[float]:
    """Fetch current Kalshi market mid using raw requests + fresh kalshi_py auth per call.
    No module-level import to avoid circular init issues. 5s timeout.
    """
    try:
        import os
        import requests
        BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
        series_map = {
            "BTC": "KXBTC15M", "ETH": "KXETH15M", "SOL": "KXSOL15M",
            "BNB": "KXBNB15M", "DOGE": "KXDOGE15M", "XRP": "KXXRP15M",
            "HYPE": "KXHYPE15M", "ADA": "KXADA15M",
        }
        series = series_map.get(coin.upper())
        if not series:
            return None

        access_key = os.getenv("KALSHI_ACCESS_KEY", "")
        private_key_path = '/home/ubuntu/.openclaw/workspace/workers/superbot/kalshi_private_key.pem'
        with open(private_key_path) as f:
            private_key_data = f.read()

        from kalshi_py.auth import KalshiAuth
        auth = KalshiAuth(access_key_id=access_key, private_key_pem=private_key_data)
        path = "/markets"
        headers = auth.get_auth_headers('GET', path)
        params = {"series_ticker": series, "status": "open", "limit": 1}
        resp = requests.get(f"{BASE_URL}{path}", headers=headers, params=params, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        markets = data.get("markets", [])
        if markets:
            m = markets[0]
            yes_bid = float(m.get("yes_bid_dollars", 0) or 0)
            yes_ask = float(m.get("yes_ask_dollars", 0) or 0)
            if yes_bid > 0 and yes_ask > 0:
                return (yes_bid + yes_ask) / 2
    except Exception as e:
        logger.debug(f"[_get_market_mid] {coin}: {e}")
    return None


def notify_discord(coin: str, side: str, conf: int, entry_max: float, signal_type: str = "CANDLE"):
    """Send signal notification to Discord."""
    emoji = "🔔" if signal_type == "CANDLE" else "⚠️"
    msg = f"{emoji} {signal_type} SIGNAL: {coin} {side} | CONF={conf} | Entry ≤${entry_max:.2f}"
    _post_discord(msg)


def notify_discord_status(msg: str):
    """Send a status update to Discord."""
    _post_discord(msg)


def _post_discord(msg: str):
    """Post a message to the Discord webhook (non-blocking, 5s timeout)."""
    try:
        resp = requests.post(
            DISCORD_WEBHOOK,
            json={"content": msg},
            timeout=5,  # Reduced from 10s to 5s to prevent hangs
        )
        if resp.status_code in (200, 204):
            logger.info(f"Discord posted: {msg}")
        elif resp.status_code == 429:
            logger.warning(f"Discord rate limited - skipping ({resp.status_code})")
        else:
            logger.warning(f"Discord post failed: {resp.status_code} {resp.text[:100]}")
    except requests.exceptions.Timeout:
        logger.warning("Discord post timed out after 5s - continuing")
    except Exception as e:
        logger.warning(f"Discord post error: {e}")


# =============================================================================
# CANDLE TRACKER
# =============================================================================
class CandleTracker:
    """
    Tracks 15-min candles for a single coin using time-based boundaries.
    Candle completes at :00, :15, :30, :45 UTC.
    """

    def __init__(self, coin: str):
        self.coin = coin
        self.product_id = COINBASE_PRODUCTS.get(coin.upper(), "")
        self.prev_utc_bucket: Optional[int] = None  # 0, 15, 30, or 45
        self.prev_close: Optional[float] = None
        self.candle_start_ts: Optional[float] = None
        self.time_above_prev: float = 0.0
        self.poll_count: int = 0
        self.last_price: Optional[float] = None
        # Regime filter: rolling window of last 3 candles' YES/NO ratios
        self.candle_ratios: list = []  # Each entry is ratio (1.0 = full YES, 0.0 = full NO)
        self.regime_skip_this_cycle: bool = False  # Skip NO signals if in bullish regime

    def _get_utc_bucket(self) -> int:
        """Return current 15-min bucket: 0, 15, 30, or 45."""
        now = datetime.utcnow()
        m = now.minute
        if m < 15:
            return 0
        elif m < 30:
            return 15
        elif m < 45:
            return 30
        else:
            return 45

    def _get_current_price(self) -> Optional[float]:
        """Fetch current price from Coinbase."""
        try:
            url = f"{COINBASE_API}/products/{self.product_id}/ticker"
            resp = requests.get(url, timeout=5)
            resp.raise_for_status()
            data = resp.json()
            return float(data.get("price", 0))
        except Exception as e:
            logger.debug(f"[{self.coin}] Price fetch error: {e}")
            return None

    def update(self) -> Optional[Dict]:
        """
        Update tracker with latest price.
        Returns a signal dict if a candle just completed, None otherwise.
        """
        if not self.product_id:
            return None

        price = self._get_current_price()
        if price is None or price <= 0:
            return None

        utc_bucket = self._get_utc_bucket()
        now_ts = time.time()

        # First poll — initialize
        if self.prev_utc_bucket is None:
            self.prev_utc_bucket = utc_bucket
            self.candle_start_ts = now_ts
            self.prev_close = price
            self.time_above_prev = 0.0
            self.last_price = price
            logger.info(f"[{self.coin}] Initialized: price={price:.2f}, bucket={utc_bucket}")
            return None

        # Same candle — track time above prev close
        if utc_bucket == self.prev_utc_bucket:
            self.poll_count += 1
            if price > self.prev_close:
                self.time_above_prev += 10  # ~10s between polls
            self.last_price = price
            return None

        # New bucket = candle completed!
        signal_data = self._analyze_completed_candle(price)

        # Reset for new candle
        self.prev_utc_bucket = utc_bucket
        self.candle_start_ts = now_ts
        self.prev_close = self.last_price  # prev close = last price of completed candle
        self.time_above_prev = 0.0
        self.poll_count = 0
        self.last_price = price

        return signal_data

    def _analyze_completed_candle(self, current_price: float) -> Optional[Dict]:
        """Analyze completed candle's time-above-prev-close ratio."""
        if self.candle_start_ts is None or self.prev_close is None:
            return None

        elapsed = time.time() - self.candle_start_ts
        if elapsed <= 0:
            return None

        ratio = self.time_above_prev / elapsed if elapsed > 0 else 0.0

        logger.info(
            f"[{self.coin}] Candle done: prev_close={self.prev_close:.2f}, "
            f"ratio={ratio:.2%} ({self.time_above_prev:.0f}s / {elapsed:.0f}s), "
            f"current={current_price:.2f}"
        )

        # Skip startup candles shorter than 5 min
        if elapsed < 300:
            logger.debug(f"[{self.coin}] Candle too short ({elapsed:.0f}s), skipping")
            return None

        # BUY YES: >90% → conf=97
        if ratio > BUY_YES_THRESHOLD:
            # BLOCK CANDLE_YES during 09:00-10:30 UTC — historical data shows 0% WR in this window (8 losses)
            hour_utc = datetime.utcnow().hour
            if 9 <= hour_utc < 11:
                logger.info(f"[{self.coin}] ◆ CANDLE_YES BLOCKED - within 09:00-10:30 UTC blackout ({hour_utc}:00 UTC)")
                return None
            conf = 97
            # Record this candle's ratio for regime tracking
            self.candle_ratios.append(ratio)
            if len(self.candle_ratios) > REGIME_WINDOW:
                self.candle_ratios.pop(0)
            # Check regime: if 3 consecutive candles >60% YES, set skip flag for NO
            if len(self.candle_ratios) >= REGIME_WINDOW:
                all_bullish = all(r > REGIME_YES_THRESHOLD for r in self.candle_ratios)
                if all_bullish:
                    self.regime_skip_this_cycle = True
                    logger.info(f"[{self.coin}] ★ BULLISH REGIME ({len(self.candle_ratios)} candles >60% YES) - NO signals will be suppressed this cycle")
            logger.info(f"[{self.coin}] ★ BUY YES SIGNAL (conf={conf})")
            mid = _get_market_mid_at_signal(self.coin)
            sig = {
                "coin": self.coin,
                "side": "YES",
                "conf": conf,
                "entry_price_max": 0.85,
                "timestamp": datetime.utcnow().isoformat(),
                "market_mid_at_signal": mid,
            }
            # Log to signal tracking - PENDING until superbot processes it
            log_entry = {
                "timestamp": sig["timestamp"],
                "coin": self.coin,
                "signal_type": "candle_YES",
                "side": "YES",
                "conf": conf,
                "entry_price_max": 0.85,
                "market_mid_at_signal": mid,
                "action": "PENDING",
                "block_reason": None,
                "settlement_result": None,
                "won": None,
            }
            # NOTE: SB handles signal_log.json writes for CANDLE signals
            # CW only writes directly when SB never sees the signal
            return sig

        # BUY NO: <30% → conf=99 (skip if in bullish regime)
        # NO works like YES: only fire when market is extended (mid > $0.55 = YES expensive = NO is cheap)
        # If mid <= $0.55, market isn't extended enough for NO — block signal
        elif ratio < BUY_NO_THRESHOLD:
            # Check YES mid price: only emit NO if market has pumped (YES > $0.52)
            # This is the "fade the pump" filter — we want the market to have moved before we short it
            mid = _get_market_mid_at_signal(self.coin)
            if mid is None:
                logger.info(f"[{self.coin}] ◆ NO SIGNAL SKIPPED - Kalshi unreachable (mid unavailable)")
                now_ts = datetime.utcnow().isoformat()
                log_entry = {
                    "timestamp": now_ts,
                    "coin": self.coin,
                    "signal_type": "candle_NO",
                    "side": "NO",
                    "conf": 99,
                    "entry_price_max": 0.85,
                    "market_mid_at_signal": None,
                    "action": "BLOCKED",
                    "block_reason": "Kalshi unreachable - skipping blind entry",
                    "settlement_result": None,
                    "won": None,
                }
                _append_signal_log(log_entry)
                return None
            elif mid <= 0.52:
                mid_str = f"{mid:.4f}"
                logger.info(f"[{self.coin}] ◆ NO SIGNAL SKIPPED - YES mid ${mid_str} <= $0.52 (no pump to fade)")
                self.candle_ratios = []
                return None
            # Check regime filter: skip NO if 3 consecutive candles showed >60% YES
            if self.regime_skip_this_cycle:
                logger.info(f"[{self.coin}] ◆ NO SIGNAL SKIPPED - BULLISH REGIME (3 consecutive YES candles >60%)")
                # Reset regime flag for next cycle
                self.regime_skip_this_cycle = False
                self.candle_ratios = []  # Reset regime tracking after suppression
                return None
            # Fetch mid for logging and include in signal
            mid = _get_market_mid_at_signal(self.coin)
            conf = 99
            mid_str = f"{mid:.4f}" if mid is not None else "N/A"
            logger.info(f"[{self.coin}] ★ BUY NO SIGNAL (conf={conf}) [mid={mid_str} > $0.55 - market extended]")
            # Successful NO signal - reset regime tracking
            self.regime_skip_this_cycle = False
            self.candle_ratios = []
            sig = {
                "coin": self.coin,
                "side": "NO",
                "conf": conf,
                "entry_price_max": 0.85,
                "timestamp": datetime.utcnow().isoformat(),
                "market_mid_at_signal": mid,
            }
            log_entry = {
                "timestamp": sig["timestamp"],
                "coin": self.coin,
                "signal_type": "candle_NO",
                "side": "NO",
                "conf": conf,
                "entry_price_max": 0.85,
                "market_mid_at_signal": mid,
                "action": "PENDING",
                "block_reason": None,
                "settlement_result": None,
                "won": None,
            }
            # NOTE: SB handles signal_log.json writes - CW does not write PENDING here
            return sig

        return None


# =============================================================================
# MACRO CORRELATION DETECTOR
# =============================================================================
class MacroCorrelationDetector:
    """
    Detects when 3+ coins fire the same direction signal within 30 seconds.
    When a macro cluster is detected, emits a MACRO_FADE signal (opposite direction)
    for all clustered coins.

    Example: BTC+ETH+SOL all emit YES within 30s → emit MACRO_FADE NO for BTC, ETH, SOL
    """

    def __init__(self, window_sec: int = MACRO_WINDOW_SEC, min_cluster: int = MACRO_MIN_CLUSTER):
        self.window_sec = window_sec
        self.min_cluster = min_cluster
        # signal_history: list of {"coin", "side", "timestamp"} sorted by time
        self.signal_history: list = []

    def record_signal(self, coin: str, side: str):
        """Record a signal (YES or NO) for a coin with current timestamp."""
        self.signal_history.append({
            "coin": coin,
            "side": side,
            "timestamp": time.time()
        })
        # Prune old entries outside the window
        cutoff = time.time() - self.window_sec
        self.signal_history = [s for s in self.signal_history if s["timestamp"] >= cutoff]

    def detect_macro_cluster(self) -> Optional[Dict]:
        """
        Check if there's a cluster of 3+ coins firing the same direction within window.
        Returns dict with cluster info if detected, None otherwise:
        {
            "coins": ["BTC", "ETH", "SOL"],
            "side": "YES",          # direction that clustered
            "fade_side": "NO",       # opposite direction for fade
            "window": 25,            # actual window size in seconds
            "count": 3
        }
        """
        if len(self.signal_history) < self.min_cluster:
            return None

        cutoff = time.time() - self.window_sec
        recent = [s for s in self.signal_history if s["timestamp"] >= cutoff]

        # Group by side
        yes_coins = list({s["coin"] for s in recent if s["side"].upper() == "YES"})
        no_coins = list({s["coin"] for s in recent if s["side"].upper() == "NO"})

        if len(yes_coins) >= self.min_cluster:
            window_size = max(s["timestamp"] for s in recent if s["coin"] in yes_coins) - \
                          min(s["timestamp"] for s in recent if s["coin"] in yes_coins)
            return {
                "coins": yes_coins,
                "side": "YES",
                "fade_side": "NO",
                "window": int(window_size),
                "count": len(yes_coins)
            }

        if len(no_coins) >= self.min_cluster:
            window_size = max(s["timestamp"] for s in recent if s["coin"] in no_coins) - \
                          min(s["timestamp"] for s in recent if s["coin"] in no_coins)
            return {
                "coins": no_coins,
                "side": "NO",
                "fade_side": "YES",
                "window": int(window_size),
                "count": len(no_coins)
            }

        return None

    def emit_macro_fade_signals(self, cluster_info: Dict) -> List[Dict]:
        """
        Generate MACRO_FADE signals for all coins in the cluster.
        Returns list of signal dicts (one per coin).
        """
        signals = []
        for coin in cluster_info["coins"]:
            mid = _get_market_mid_at_signal(coin)
            signal = {
                "signal_type": "MACRO_FADE",
                "coin": coin,
                "side": cluster_info["fade_side"],
                "confidence": 60,
                "entry_price": mid,
                "market_mid_at_signal": mid,
                "is_candle_duration": False,
                "reason": f"MACRO FADE: {cluster_info['count']} coins {cluster_info['side']} in {cluster_info['window']}s",
                "timestamp": datetime.utcnow().isoformat(),
                "cluster_coins": cluster_info["coins"],
                "cluster_side": cluster_info["side"],
            }
            signals.append(signal)

            # Log to signal_log.json
            log_entry = {
                "timestamp": signal["timestamp"],
                "coin": coin,
                "signal_type": "MACRO_FADE",
                "side": signal["side"],
                "conf": signal["confidence"],
                "entry_price": signal["entry_price"],
                "market_mid_at_signal": mid,
                "action": "PENDING",
                "block_reason": None,
                "settlement_result": None,
                "won": None,
                "cluster_coins": cluster_info["coins"],
                "cluster_side": cluster_info["side"],
                "reason": signal["reason"]
            }
            # NOTE: SB handles signal_log.json writes for MACRO signals

        return signals

    def emit_macro_ride_signals(self, cluster_info: Dict) -> List[Dict]:
        """
        MOMENTUM-FOLLOWING VARIANT (paper test):
        When 7+ coins fire the same direction within 30s, emit MACRO_RIDE signals
        in the SAME direction (ride the pump, don't fade it).
        
        This is the opposite of MACRO_FADE. Only fires on 7+ coin clusters.
        Conf=65 (slightly higher than fade since we don't have historical data).
        Sizing capped at $0.50/trade until we have n>=15.
        """
        if cluster_info['count'] < 7:
            return []  # Only fire on big clusters

        signals = []
        for coin in cluster_info["coins"]:
            mid = _get_market_mid_at_signal(coin)
            signal = {
                "signal_type": "MACRO_RIDE",
                "coin": coin,
                "side": cluster_info["side"],  # SAME direction as cluster (not opposite)
                "confidence": 65,
                "entry_price": mid,
                "market_mid_at_signal": mid,
                "is_candle_duration": False,
                "reason": f"MACRO RIDE: {cluster_info['count']} coins {cluster_info['side']} in {cluster_info['window']}s (ride momentum)",
                "timestamp": datetime.utcnow().isoformat(),
                "cluster_coins": cluster_info["coins"],
                "cluster_side": cluster_info["side"],
            }
            signals.append(signal)

            # Log to signal_log.json
            log_entry = {
                "timestamp": signal["timestamp"],
                "coin": coin,
                "signal_type": "MACRO_RIDE",
                "side": signal["side"],
                "conf": signal["confidence"],
                "entry_price": signal["entry_price"],
                "market_mid_at_signal": mid,
                "action": "PENDING",
                "block_reason": None,
                "settlement_result": None,
                "won": None,
                "cluster_coins": cluster_info["coins"],
                "cluster_side": cluster_info["side"],
                "reason": signal["reason"]
            }
            # NOTE: SB handles signal_log.json writes for MACRO signals

        return signals


# =============================================================================
# =============================================================================
# OPEN ORDER PLACEMENT (Tony's edge play)
# Any coin, any side, if <= $0.15 → buy $1 limit order at $0.15
# Poll every 5 seconds to catch markets as they open
# =============================================================================
OPEN_ORDER_MAX_PRICE = 0.15
OPEN_ORDER_AMOUNT = 1.00  # $1 per side
OPEN_ORDER_COOLDOWN = 90  # don't play same ticker within 90 seconds

# Track tickers we've already played
_played_tickers: Dict[str, float] = {}  # ticker -> last_play_timestamp


def _cleanup_stale_tickers():
    """Remove tickers from cooldown."""
    now = time.time()
    stale = [t for t, ts in _played_tickers.items() if now - ts > OPEN_ORDER_COOLDOWN]
    for t in stale:
        del _played_tickers[t]


def check_and_place_open_orders(kalshi_api: 'KalshiAPI'):
    """
    Tony's edge play: Any side <= $0.15 on any market → buy $1 limit order.
    Simple. Fast. Early.
    """
    _cleanup_stale_tickers()
    
    for coin, series in SERIES_TICKERS.items():
        try:
            markets = kalshi_api.get_open_markets(series)
            if not markets:
                continue
            
            market = markets[0]
            ticker = market.ticker
            
            if ticker in _played_tickers:
                continue
            
            yes_bid = getattr(market, 'yes_bid', None) or 0
            yes_ask = getattr(market, 'yes_ask', None) or 0
            no_bid = getattr(market, 'no_bid', None) or 0
            no_ask = getattr(market, 'no_ask', None) or 0
            
            if not (yes_bid > 0 and yes_ask > 0 and no_bid > 0 and no_ask > 0):
                continue
            
            
            # Check each side independently
            sides_placed = []
            
            if yes_bid <= OPEN_ORDER_MAX_PRICE:
                # YES is cheap — buy YES
                result = kalshi_api.place_order(
                    ticker=ticker, side='yes', price=OPEN_ORDER_MAX_PRICE,
                    amount=OPEN_ORDER_AMOUNT, action='buy', order_type='limit'
                )
                order_id = result.get('order', {}).get('order_id') if 'order' in result else None
                if order_id:
                    logger.info(f"OPEN ORDER: {ticker} YES bought @ ${OPEN_ORDER_MAX_PRICE:.2f} (bid={yes_bid:.4f})")
                    sides_placed.append(('YES', order_id))
                else:
                    logger.warning(f"OPEN ORDER: {ticker} YES failed: {result}")
            
            if no_bid <= OPEN_ORDER_MAX_PRICE:
                # NO is cheap — buy NO
                result = kalshi_api.place_order(
                    ticker=ticker, side='no', price=OPEN_ORDER_MAX_PRICE,
                    amount=OPEN_ORDER_AMOUNT, action='buy', order_type='limit'
                )
                order_id = result.get('order', {}).get('order_id') if 'order' in result else None
                if order_id:
                    logger.info(f"OPEN ORDER: {ticker} NO bought @ ${OPEN_ORDER_MAX_PRICE:.2f} (bid={no_bid:.4f})")
                    sides_placed.append(('NO', order_id))
                else:
                    logger.warning(f"OPEN ORDER: {ticker} NO failed: {result}")
            
            if sides_placed:
                _played_tickers[ticker] = time.time()  # Mark as played
                
        except Exception as e:
            logger.debug(f"OPEN ORDER: {coin} error: {e}")


# MAIN LOOP
# =============================================================================
macro_detector = MacroCorrelationDetector()
def main():
    logger.info("=" * 60)
    logger.info("CANDLE WATCHER STARTING - 24/7 Persistent Process")
    logger.info(f"Watching coins: {list(COINBASE_PRODUCTS.keys())}")
    logger.info(f"YES threshold: >{BUY_YES_THRESHOLD:.0%} (conf=97)")
    logger.info(f"NO threshold: <{BUY_NO_THRESHOLD:.0%} (conf=99)")
    logger.info("=" * 60)

    trackers = {coin: CandleTracker(coin) for coin in COINBASE_PRODUCTS}
    kalshi_api = KalshiAPI(KALSHI_ACCESS_KEY)  # For pre-open order placement
    poll_interval = 5  # seconds - fast polling to catch market opens
    last_status_bucket: Optional[int] = None  # 0, 15, 30, or 45

    def shutdown_handler(signum, frame):
        logger.info("Shutdown signal received - exiting gracefully")
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)

    while True:
        for coin, tracker in trackers.items():
            try:
                signal_data = tracker.update()
                if signal_data:
                    # Record in macro detector
                    macro_detector.record_signal(signal_data["coin"], signal_data["side"])

                    # Check for macro cluster BEFORE writing to file
                    cluster = macro_detector.detect_macro_cluster()
                    if cluster:
                        logger.info(f"⚠️ MACRO CLUSTER DETECTED: {cluster['count']} coins {cluster['side']} in {cluster['window']}s → FADE {cluster['fade_side']}")
                        macro_signals = macro_detector.emit_macro_fade_signals(cluster)
                        for msig in macro_signals:
                            # Write each macro fade signal to its coin's signal file
                            macro_file = get_signal_file(msig["coin"])
                            with open(macro_file, "w") as f:
                                json.dump(msig, f, indent=2)
                            logger.info(f"MACRO FADE signal saved to {macro_file}: {msig}")
                            notify_discord(
                                msig["coin"],
                                msig["side"],
                                msig["confidence"],
                                0.85,  # entry_price_max not in macro signal, use default
                                "MACRO_FADE"
                            )



                        # Also emit MACRO_RIDE signals for 7+ coin clusters (momentum-following paper test)
                        # Write to SEPARATE file so both strategies can be processed independently
                        ride_signals = macro_detector.emit_macro_ride_signals(cluster)
                        for rsig in ride_signals:
                            macro_ride_file = get_macro_ride_file(rsig["coin"])
                            with open(macro_ride_file, "w") as f:
                                json.dump(rsig, f, indent=2)
                            logger.info(f"🌊 MACRO RIDE signal saved to {macro_ride_file}: {rsig}")

                    # Write normal signal
                    signal_file = get_signal_file(coin)
                    with open(signal_file, "w") as f:
                        json.dump(signal_data, f, indent=2)
                    logger.info(f"Signal saved to {signal_file}: {signal_data}")
                    notify_discord(
                        signal_data["coin"],
                        signal_data["side"],
                        signal_data["conf"],
                        signal_data["entry_price_max"],
                        "CANDLE"
                    )
            except Exception as e:
                logger.error(f"[{coin}] Tracker error: {e}")

        # Check if we hit a new 15-min boundary → post status
        current_bucket = (datetime.utcnow().minute // 15) * 15
        if last_status_bucket is not None and current_bucket != last_status_bucket:
            # A new 15-min mark was crossed — determine which coins had signals this candle
            coins_with_signal = []
            for coin, tracker in trackers.items():
                if tracker.last_price is not None:
                    # We'll just report "Watching" unless there's a signal to report
                    pass
            notify_discord_status("Watching - no signals this candle")

        last_status_bucket = current_bucket

        # === OPEN ORDERS: Check all markets for cheap both-sides fills ===
        # No signal required — if both YES and NO are <= $0.15, we play
        try:
            check_and_place_open_orders(kalshi_api)
        except Exception as e:
            logger.error(f"OPEN ORDERS: check failed: {e}")

        time.sleep(poll_interval)


if __name__ == "__main__":
    main()
