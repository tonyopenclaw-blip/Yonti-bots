#!/usr/bin/env python3
"""
📊 Recorder Bot - Market Data Collection
Records second-by-second price data for 15-min crypto prediction markets.
Later, Nerd will analyze this data to find patterns that predict final outcomes.
"""

import logging
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
import threading
import sys

from config import (
    LOG_FILE, LOG_LEVEL, LOG_FORMAT, LOG_DATE_FORMAT,
    DATA_FILE, POLL_INTERVAL_SEC, SERIES_TICKERS, COINS,
    IDLE_POLL_INTERVAL_SEC, ACTIVE_POLL_INTERVAL_SEC
)
from kalshi_api import KalshiAPI, Market

# =============================================================================
# LOGGING SETUP
# =============================================================================
LOG_FILE.parent.mkdir(exist_ok=True)
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format=LOG_FORMAT,
    datefmt=LOG_DATE_FORMAT,
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Fun personality messages
FUN_MESSAGES = [
    "📊 Recorder here! Spotted a juicy market, going to town on it!",
    "🖊️ Recording in progress... this data's gonna be SPPICY!",
    "📈 Tick tick tick! Every second counts in this game!",
    "🔍 Scanner found something? Nope, just little old me, recording away!",
    "🍿 Popcorn ready! Watching these markets so Nerd can crunch the numbers later!",
    "💾 Storing precious data bytes... future Nerd will thank me!",
    "⚡ FAST poll engaged! Nothing gets past this recorder!",
    "🎯 Found an active one! Starting data collection sequence...",
    "📡 Signal acquired! Locking onto market data stream...",
    "🧠 Brains and bytes! Recording markets for the masterminds!",
]


class MarketRecord:
    """Represents a market being recorded with all its samples."""
    
    def __init__(self, market: Market):
        self.ticker = market.ticker
        self.coin = _extract_coin(market.ticker)
        self.open_time = market.close_time  # We'll get actual open time
        self.close_time = market.close_time
        self.result: Optional[str] = None
        self.samples: list = []
        self.start_ts: datetime = datetime.now(timezone.utc)
        self._closed = False
    
    def add_sample(self, market: Market) -> None:
        """Add a price sample at the current second."""
        if self._closed:
            return
        
        second = self._calc_second()
        self.samples.append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "second": second,
            "yes_bid": market.yes_bid,
            "yes_ask": market.yes_ask
        })
    
    def _calc_second(self) -> int:
        """Calculate seconds elapsed since recording started."""
        delta = datetime.now(timezone.utc) - self.start_ts
        return int(delta.total_seconds())
    
    def finalize(self, result: Optional[str]) -> None:
        """Finalize record when market closes."""
        self.result = result
        self._closed = True
    
    def calc_pct_above_50(self) -> float:
        """Calculate cumulative % of samples where YES > 0.50."""
        if not self.samples:
            return 0.0
        above_50 = sum(1 for s in self.samples if s["yes_bid"] > 0.50)
        return above_50 / len(self.samples)
    
    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "ticker": self.ticker,
            "coin": self.coin,
            "open_time": self.start_ts.isoformat(),
            "close_time": self.close_time,
            "result": self.result,
            "pct_above_50": self.calc_pct_above_50(),
            "total_samples": len(self.samples),
            "samples": self.samples
        }


def _extract_coin(ticker: str) -> str:
    """Extract coin symbol from ticker."""
    parts = ticker.split("-")
    if parts:
        series = parts[0]
        if series.startswith("KX") and "15M" in series:
            return series[2:5]
    return "UNK"


class Recorder:
    """
    📊 The Recorder - Obsessive market data collector!
    
    Watches 15-min crypto markets and records every single second
    of price action. Because Nerd needs those sweet sweet patterns!
    
    Smart polling strategy:
    - When NO markets are active: poll every 10 seconds (idle mode)
    - When markets ARE active: poll every 1 second (active mode)
    - Uses /markets endpoint with status=open filter (1 API call vs 8)
    - Tracks which markets are recording to avoid re-fetching
    - Exponential backoff on 429 rate limit errors
    """
    
    def __init__(self):
        self.api = KalshiAPI()
        self.active_recordings: Dict[str, MarketRecord] = {}
        self.data_file = Path(DATA_FILE)
        self.running = True
        self.poll_count = 0
        
        # Rate limit backoff state
        self.rate_limited_until: float = 0
        self.backoff_seconds = 0
        
        # Our series tickers list for efficient API calls
        self.our_series_tickers = list(SERIES_TICKERS.values())
        
        # Track which series have active markets - prioritize polling them
        self.active_series: set = set()
        
        # Cycle counter for idle polling through all 8 series
        self.series_cycle = 0
        
        logger.info("=" * 60)
        logger.info("📊 RECORDER BOT INITIALIZED!")
        logger.info("Purpose: Record second-by-second market data for Nerd's analysis")
        logger.info(f"Watching {len(COINS)} coin series: {', '.join(COINS)}")
        logger.info(f"Idle poll interval: {IDLE_POLL_INTERVAL_SEC}s | Active poll interval: {ACTIVE_POLL_INTERVAL_SEC}s")
        logger.info("=" * 60)
    
    def save_record(self, record: MarketRecord) -> None:
        """Append record to JSONL file."""
        with open(self.data_file, "a") as f:
            f.write(json.dumps(record.to_dict()) + "\n")
        
        pct = record.calc_pct_above_50()
        logger.info(
            f"💾 SAVED {record.ticker} | Coin: {record.coin} | "
            f"Result: {record.result} | Samples: {len(record.samples)} | "
            f"Pct>50: {pct:.1%}"
        )
    
    def check_for_new_markets(self, series_ticker: str) -> bool:
        """
        Check for NEW markets to start recording for a SINGLE series_ticker.
        Updates active_series set based on what markets are found.
        Returns True if any new markets were found.
        """
        # Get open markets for this ONE series
        all_markets = self.api.get_open_markets(series_ticker)
        
        # Track which series have active markets
        series_has_active = False
        
        if not all_markets:
            # Remove from active_series if no markets found
            self.active_series.discard(series_ticker)
            return False
        
        new_found = False
        for market in all_markets:
            # Skip if already recording this market
            if market.ticker in self.active_recordings:
                series_has_active = True
                continue
            
            # New market! Start recording!
            record = MarketRecord(market)
            self.active_recordings[market.ticker] = record
            series_has_active = True
            
            coin = _extract_coin(market.ticker)
            fun_msg = FUN_MESSAGES[self.poll_count % len(FUN_MESSAGES)]
            logger.info(f"🎯 {fun_msg}")
            logger.info(
                f"📊 Started recording {market.ticker} ({coin}) | "
                f"Close: {market.close_time} | "
                f"Price: ${market.yes_bid:.2f}-${market.yes_ask:.2f}"
            )
            new_found = True
        
        if series_has_active:
            self.active_series.add(series_ticker)
        else:
            self.active_series.discard(series_ticker)
        
        return new_found
    
    def poll_active_markets(self, series_ticker: str) -> None:
        """
        Poll active markets for a SINGLE series, collecting samples and checking for closure.
        """
        # Get open markets for this ONE series
        all_markets = self.api.get_open_markets(series_ticker)
        market_lookup: Dict[str, Market] = {m.ticker: m for m in all_markets}
        
        tickers_to_remove = []
        
        for ticker, record in self.active_recordings.items():
            market = market_lookup.get(ticker)
            
            if market:
                # Market still exists and is open
                record.add_sample(market)
                
                # Log every 5 seconds for fun
                if record._calc_second() % 5 == 0:
                    logger.debug(
                        f"📈 {ticker} | Sec {record._calc_second()} | "
                        f"${market.yes_bid:.2f}-${market.yes_ask:.2f}"
                    )
            else:
                # Market disappeared - might be settled, check
                result = self.api.get_market_result(ticker)
                if result is not None:
                    record.finalize(result)
                    self.save_record(record)
                    tickers_to_remove.append(ticker)
                    logger.info(f"🏁 Market finalized {ticker} (no longer in open list)")
        
        # Remove closed markets
        for ticker in tickers_to_remove:
            del self.active_recordings[ticker]
    
    def run(self) -> None:
        """
        Main loop - poll for markets and collect data.
        
        Smart polling (Kalshi only accepts ONE series_ticker per request):
        - When NO markets active: poll ONE series per cycle, cycle through all 8 series
          (each series checked every 80 seconds = 8 series × 10 sec)
        - When markets ARE active: poll THAT series every 1 second
        - Exponential backoff on 429 rate limit (30s, 60s, 120s)
        """
        logger.info("🚀 Recorder starting main loop... Let's get some DATA!")
        
        while self.running:
            self.poll_count += 1
            
            # Check if we're in rate limit backoff
            now = time.time()
            if now < self.rate_limited_until:
                wait_time = self.rate_limited_until - now
                logger.info(f"⏳ Rate limit backoff: waiting {wait_time:.0f}s...")
                time.sleep(min(wait_time, 5))  # Sleep in smaller chunks
                continue
            
            try:
                if self.active_series:
                    # Active mode: poll each active series every 1 second
                    for series_ticker in list(self.active_series):
                        self.check_for_new_markets(series_ticker)
                        if self.active_recordings:
                            self.poll_active_markets(series_ticker)
                    time.sleep(ACTIVE_POLL_INTERVAL_SEC)
                else:
                    # Idle mode: check ONE series per cycle, cycle through all 8
                    series_ticker = self.our_series_tickers[self.series_cycle % len(self.our_series_tickers)]
                    self.series_cycle += 1
                    
                    self.check_for_new_markets(series_ticker)
                    
                    if self.active_recordings:
                        # Markets appeared! Don't sleep, immediately start active polling
                        if self.poll_count % 30 == 1:
                            logger.debug(
                                f"😴 Idle mode: checked {series_ticker} "
                                f"(poll #{self.poll_count})"
                            )
                    else:
                        if self.poll_count % 30 == 1:
                            logger.debug(
                                f"😴 No active markets right now... "
                                f"checked {series_ticker} "
                                f"(poll #{self.poll_count})"
                            )
                        time.sleep(IDLE_POLL_INTERVAL_SEC)
                
            except KeyboardInterrupt:
                logger.info("⏹️ Recorder shutting down gracefully...")
                self.running = False
            except Exception as e:
                logger.error(f"❌ Error in main loop: {e}")
                time.sleep(5)  # Back off on error
        
        # Finalize any remaining recordings
        logger.info("📝 Finalizing remaining recordings...")
        for ticker, record in self.active_recordings.items():
            result = self.api.get_market_result(ticker)
            record.finalize(result)
            self.save_record(record)
        
        logger.info("👋 Recorder done! Data saved. Go Nerd, do your thing!")


def main():
    """Entry point."""
    recorder = Recorder()
    recorder.run()


if __name__ == "__main__":
    main()
