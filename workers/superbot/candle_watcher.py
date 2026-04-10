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
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import requests

# =============================================================================
# CONFIG
# =============================================================================
BASE_DIR = Path(__file__).parent
SIGNALS_FILE = BASE_DIR / "candle_signals.json"
LOG_FILE = BASE_DIR / "candle_watcher.log"

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

DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1486066262122430684/mLKWVlGJRyADWEnpDgx3n4QcI1B-JhAnDLyBHKwsK-BSmeo5lal5MYrrY_QiuOBqiNLY"

# Only apply tier-2 logic to these coins (HYPE/XRP excluded due to <70% win rate)
TIER2_COINS = {"BTC", "ETH", "SOL", "BNB", "DOGE", "ADA"}

# Signal thresholds
BUY_YES_THRESHOLD = 0.90  # >90% of candle time above prev close → Tier 1 BUY YES (conf=95)
BUY_YES_TIER2 = 0.60       # 60-80% → Tier 2 BUY YES (conf=72)
BUY_NO_THRESHOLD = 0.40  # <40% → BUY NO

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
# DISCORD NOTIFICATION
# =============================================================================
def notify_discord(coin: str, side: str, conf: int, tier: int, entry_max: float):
    """Send signal notification to Discord."""
    tier_emoji = "🔶" if tier == 2 else "🔔"
    msg = f"{tier_emoji} CANDLE SIGNAL: {coin} {side} | TIER={tier} | CONF={conf} | Entry ≤${entry_max:.2f}"
    try:
        resp = requests.post(
            DISCORD_WEBHOOK,
            json={"content": msg},
            timeout=10,
        )
        if resp.status_code in (200, 204):
            logger.info(f"Discord notified: {msg}")
        else:
            logger.warning(f"Discord notify failed: {resp.status_code} {resp.text}")
    except Exception as e:
        logger.error(f"Discord notify error: {e}")


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

        if ratio > BUY_YES_THRESHOLD:
            conf = 95
            tier = 1
            logger.info(f"[{self.coin}] ★ BUY YES SIGNAL (Tier {tier}, conf={conf})")
            return {
                "coin": self.coin,
                "side": "YES",
                "conf": conf,
                "tier": tier,
                "entry_price_max": 0.85,
                "timestamp": datetime.utcnow().isoformat(),
            }

        # Tier 2: 60-80% → BUY YES with conf=72 (only for eligible coins)
        elif ratio > BUY_YES_TIER2 and self.coin.upper() in TIER2_COINS:
            conf = 72
            tier = 2
            logger.info(f"[{self.coin}] ★ BUY YES SIGNAL (Tier {tier}, conf={conf})")
            return {
                "coin": self.coin,
                "side": "YES",
                "conf": conf,
                "tier": tier,
                "entry_price_max": 0.85,
                "timestamp": datetime.utcnow().isoformat(),
            }

        elif ratio < BUY_NO_THRESHOLD:
            conf = int(min(99, 50 + (BUY_NO_THRESHOLD - ratio) * 500))
            logger.info(f"[{self.coin}] ★ BUY NO SIGNAL (conf={conf})")
            return {
                "coin": self.coin,
                "side": "NO",
                "conf": conf,
                "entry_price_max": 0.85,
                "timestamp": datetime.utcnow().isoformat(),
            }

        return None


# =============================================================================
# MAIN LOOP
# =============================================================================
def main():
    logger.info("=" * 60)
    logger.info("CANDLE WATCHER STARTING - 24/7 Persistent Process")
    logger.info(f"Watching coins: {list(COINBASE_PRODUCTS.keys())}")
    logger.info("=" * 60)

    trackers = {coin: CandleTracker(coin) for coin in COINBASE_PRODUCTS}
    poll_interval = 10  # seconds

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
                    with open(SIGNALS_FILE, "w") as f:
                        json.dump(signal_data, f, indent=2)
                    logger.info(f"Signal saved to {SIGNALS_FILE}: {signal_data}")
                    notify_discord(
                        signal_data["coin"],
                        signal_data["side"],
                        signal_data["conf"],
                        signal_data.get("tier", 1),
                        signal_data["entry_price_max"],
                    )
            except Exception as e:
                logger.error(f"[{coin}] Tracker error: {e}")

        time.sleep(poll_interval)


if __name__ == "__main__":
    main()
