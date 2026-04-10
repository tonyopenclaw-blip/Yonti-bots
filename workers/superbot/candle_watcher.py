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
from typing import Dict, Optional

import requests

# =============================================================================
# CONFIG
# =============================================================================
BASE_DIR = Path(__file__).parent
SIGNALS_DIR = BASE_DIR / "candle_signals"
LOG_FILE = BASE_DIR / "candle_watcher.log"

# Ensure candle_signals directory exists
SIGNALS_DIR.mkdir(exist_ok=True)

def get_signal_file(coin: str) -> Path:
    """Return the per-coin signal file path."""
    return SIGNALS_DIR / f"{coin}.json"

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

# Signal thresholds
BUY_YES_THRESHOLD = 0.90  # >90% of candle time above prev close → BUY YES (conf=95)
BUY_NO_THRESHOLD = 0.30   # <30% → BUY NO (conf=99)

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
def notify_discord(coin: str, side: str, conf: int, entry_max: float):
    """Send signal notification to Discord."""
    msg = f"🔔 CANDLE SIGNAL: {coin} {side} | CONF={conf} | Entry ≤${entry_max:.2f}"
    _post_discord(msg)


def notify_discord_status(msg: str):
    """Send a status update to Discord."""
    _post_discord(msg)


def _post_discord(msg: str):
    """Post a message to the Discord webhook."""
    try:
        resp = requests.post(
            DISCORD_WEBHOOK,
            json={"content": msg},
            timeout=10,
        )
        if resp.status_code in (200, 204):
            logger.info(f"Discord posted: {msg}")
        else:
            logger.warning(f"Discord post failed: {resp.status_code} {resp.text}")
    except Exception as e:
        logger.error(f"Discord post error: {e}")


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

        # BUY YES: >90% → conf=95
        if ratio > BUY_YES_THRESHOLD:
            conf = 95
            logger.info(f"[{self.coin}] ★ BUY YES SIGNAL (conf={conf})")
            return {
                "coin": self.coin,
                "side": "YES",
                "conf": conf,
                "entry_price_max": 0.85,
                "timestamp": datetime.utcnow().isoformat(),
            }

        # BUY NO: <30% → conf=99
        elif ratio < BUY_NO_THRESHOLD:
            conf = 99
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
    logger.info(f"YES threshold: >{BUY_YES_THRESHOLD:.0%} (conf=95)")
    logger.info(f"NO threshold: <{BUY_NO_THRESHOLD:.0%} (conf=99)")
    logger.info("=" * 60)

    trackers = {coin: CandleTracker(coin) for coin in COINBASE_PRODUCTS}
    poll_interval = 10  # seconds
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
                    signal_file = get_signal_file(coin)
                    with open(signal_file, "w") as f:
                        json.dump(signal_data, f, indent=2)
                    logger.info(f"Signal saved to {signal_file}: {signal_data}")
                    notify_discord(
                        signal_data["coin"],
                        signal_data["side"],
                        signal_data["conf"],
                        signal_data["entry_price_max"],
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

        time.sleep(poll_interval)


if __name__ == "__main__":
    main()
