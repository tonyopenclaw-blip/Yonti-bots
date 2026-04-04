#!/usr/bin/env python3
# thermostat.py - Weather Forecast Arbitrage Bot for Kalshi Climate Markets
#
# Strategy: Compare NOAA/NWS forecasts against Kalshi climate market lines.
# When NOAA projects a higher/lower temperature than the market expects,
# we buy the OVER/UNDER position with the edge.
#
# Paper trading only. $100 starting balance. $2 max bet per market.

import json
import logging
import re
import signal
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any

import requests

from config import (
    LOG_FILE, LOG_LEVEL, LOG_FORMAT, LOG_DATE_FORMAT,
    PAPER_MODE, PAPER_BALANCE, MAX_BET, MIN_BET,
    CITIES, NOAA_BASE_URL,
    AGGRESSIVE_POLL_START, AGGRESSIVE_POLL_END, AGGRESSIVE_INTERVAL, NORMAL_INTERVAL,
    CLIMATE_SERIES_PATTERNS,
    TRADES_FILE, STATS_FILE, DATA_DIR
)
from kalshi_api import KalshiAPI, Market

# =============================================================================
# LOGGING SETUP
# =============================================================================

DATA_DIR.mkdir(exist_ok=True, parents=True)

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


# =============================================================================
# NOAA WEATHER CLIENT
# =============================================================================

class NOAAClient:
    """Fetches forecasts from NOAA National Weather Service API."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Thermostat/1.0 (weather arbitrage bot)",
            "Accept": "application/geo+json"
        })
        self.cache: Dict[str, dict] = {}
        self.cache_time: Dict[str, float] = {}
        self.cache_ttl = 1800  # 30 min cache

    def get_forecast(self, city_key: str, city_config: dict) -> Optional[Dict]:
        """
        Fetch 7-day forecast for a city from NWS API.
        Returns dict with 'highs', 'lows', 'daily' forecasts.
        """
        cache_key = city_key
        now = time.time()

        if cache_key in self.cache and (now - self.cache_time.get(cache_key, 0)) < self.cache_ttl:
            return self.cache[cache_key]

        lat = city_config["lat"]
        lon = city_config["lon"]

        try:
            # Step 1: Get the grid point for this lat/lon
            points_url = f"{NOAA_BASE_URL}/points/{lat},{lon}"
            resp = self.session.get(points_url, timeout=10)
            resp.raise_for_status()
            points_data = resp.json()

            # Get forecast URL from points response
            forecast_url = points_data["properties"]["forecast"]

            # Step 2: Get the actual forecast
            resp = self.session.get(forecast_url, timeout=10)
            resp.raise_for_status()
            forecast_data = resp.json()

            # Parse periods
            periods = forecast_data.get("properties", {}).get("periods", [])

            daily_forecasts = []
            highs = []
            lows = []

            for period in periods[:14]:  # ~7 days (day + night)
                temp = period.get("temperature", 0)
                is_daytime = period.get("isDaytime", True)
                name = period.get("name", "")

                # Extract temperature value
                if isinstance(temp, (int, float)):
                    if is_daytime:
                        highs.append(temp)
                    else:
                        lows.append(temp)

                    daily_forecasts.append({
                        "name": name,
                        "temp_f": temp,
                        "is_daytime": is_daytime,
                        "short_forecast": period.get("shortForecast", ""),
                        "detailed_forecast": period.get("detailedForecast", "")
                    })

            result = {
                "city_key": city_key,
                "city_name": city_config["name"],
                "fetched_at": datetime.utcnow().isoformat(),
                "highs": highs[:7],  # 7 high temps
                "lows": lows[:7],   # 7 low temps
                "daily": daily_forecasts[:14],
                "today_high": highs[0] if highs else None,
                "today_low": lows[0] if lows else None,
                "tomorrow_high": highs[1] if len(highs) > 1 else None
            }

            self.cache[cache_key] = result
            self.cache_time[cache_key] = now

            logger.info(f"NOAA forecast for {city_config['name']}: Today High {result.get('today_high')}°F, "
                       f"Tomorrow High {result.get('tomorrow_high')}°F")

            return result

        except Exception as e:
            logger.error(f"Failed to fetch NOAA forecast for {city_key}: {e}")
            return None

    def get_all_forecasts(self) -> Dict[str, Dict]:
        """Fetch forecasts for all configured cities."""
        forecasts = {}
        for city_key, city_config in CITIES.items():
            forecast = self.get_forecast(city_key, city_config)
            if forecast:
                forecasts[city_key] = forecast
        return forecasts


# =============================================================================
# CLIMATE MARKET PARSER
# =============================================================================

class ClimateMarketParser:
    """
    Parses Kalshi climate market data to extract temperature info.

    Relies on API's strike_type and sub_title fields rather than question text.
    Ticker format: KXHIGH{city}{date}-{T/B}{threshold}
      T = threshold (greater/less depending on strike_type API field)
      B = between (1°F range centered on threshold)
    """

    # City series prefix to city key mapping
    SERIES_TO_CITY = {
        "KXHIGHNY": "NYC", "KXHIGHTNYC": "NYC", "HIGHNY": "NYC",
        "KXHIGHTPHX": "PHX", "KXHIGHPHX": "PHX",
        "KXHIGHCHI": "CHI", "KXHIGHTCHI": "CHI",
        "KXHIGHTHOU": "HOU", "KXHIGHT Houston": "HOU",
        "KXHIGHTATL": "ATL", "KXHIGHATL": "ATL",
        "KXHIGHLAX": "LAX", "KXHIGHTLAX": "LAX", "KXLOWTLAX": "LAX",
        "KXHIGHTDEN": "DEN", "KXHIGHDEN": "DEN",
        "KXHIGHTPHL": "PHL", "KXHIGHPHL": "PHL",
        "KXHIGHTSATX": "SAT", "KXHIGHTATX": "SAT",
        "KXHIGHTSD": "SD", "KXHIGHT San Diego": "SD",
        "KXHIGHMIA": "MIA", "KXHIGHTMIA": "MIA",
        "KXHIGHTSEA": "SEA", "KXHIGHSEA": "SEA",
        "KXHIGHTBOS": "BOS", "KXHIGHBOS": "BOS",
        "KXHIGHTLV": "LV", "KXHIGHT Las Vegas": "LV",
        "KXHIGHTDAL": "DAL", "KXHIGHDAL": "DAL",
    }

    def parse_ticker(self, ticker: str) -> Optional[Dict]:
        """
        Parse a climate market ticker to extract series and threshold.
        Format: KXHIGH{city}-{DDMONYY}-{T/B}{threshold}
        Example: KXHIGHNY-26APR02-T61
                 KXHIGHTPHX-26APR02-B86.5
        """
        try:
            parts = ticker.split("-")
            if len(parts) < 3:
                return None

            series_prefix = parts[0]
            suffix = parts[2]

            city_key = self.SERIES_TO_CITY.get(series_prefix)
            if not city_key:
                return None

            if suffix.startswith("T"):
                threshold = float(suffix[1:])
                return {"city_key": city_key, "series": series_prefix, "threshold": threshold, "suffix_type": "threshold"}
            elif suffix.startswith("B"):
                threshold = float(suffix[1:])
                return {"city_key": city_key, "series": series_prefix, "threshold": threshold, "suffix_type": "between"}

            return None
        except (ValueError, IndexError):
            return None

    def parse_market_api(self, market_data: Dict) -> Optional[Dict]:
        """
        Parse full market data from Kalshi API response.
        Uses strike_type from API to determine direction.
        """
        ticker = market_data.get("ticker", "")
        strike_type = market_data.get("strike_type", "")  # 'greater', 'less', 'between'
        sub_title = market_data.get("yes_sub_title", "")

        parsed = self.parse_ticker(ticker)
        if not parsed:
            return None

        threshold = parsed["threshold"]
        suffix_type = parsed["suffix_type"]

        if strike_type == "greater":
            direction = "over"
            effective_low = threshold + 1  # YES = threshold+1°F or above
            effective_high = 999
        elif strike_type == "less":
            direction = "under"
            effective_low = -999
            effective_high = threshold - 1  # YES = threshold-1°F or below
        elif strike_type == "between":
            direction = "range"
            effective_low = threshold
            effective_high = threshold + 1
        else:
            if suffix_type == "threshold":
                direction = "over"
                effective_low = threshold
                effective_high = 999
            else:
                return None

        return {
            "city_key": parsed["city_key"],
            "series": parsed["series"],
            "ticker": ticker,
            "strike_type": strike_type,
            "direction": direction,
            "threshold": threshold,
            "effective_low": effective_low,
            "effective_high": effective_high,
            "sub_title": sub_title,
            "question": market_data.get("title", ""),
            "close_time": market_data.get("close_time"),
            "open_time": market_data.get("open_time"),
            "yes_bid": float(market_data.get("yes_bid_dollars", 0)),
            "yes_ask": float(market_data.get("yes_ask_dollars", 1)),
            "market_type": market_data.get("market_type", "binary"),
        }

    def parse(self, question: str) -> Optional[Dict]:
        """Legacy method - just parses question text."""
        return None  # Deprecated, use parse_market_api instead


# =============================================================================
# PAPER TRADING LEDGER
# =============================================================================

class PaperLedger:
    """Manages paper trading balance and trade records."""

    def __init__(self, starting_balance: float = PAPER_BALANCE):
        self.balance = starting_balance
        self.trades: List[Dict] = []
        self.stats = {
            "starting_balance": starting_balance,
            "current_balance": starting_balance,
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "pending_trades": 0,
            "total_pnl": 0.0,
            "win_rate": 0.0,
            "avg_pnl": 0.0
        }
        self._load_data()

    def _load_data(self):
        """Load existing trades and stats from disk."""
        if TRADES_FILE.exists():
            try:
                data = json.loads(TRADES_FILE.read_text())
                self.trades = data.get("trades", [])
                self.stats = data.get("stats", self.stats)
                self.balance = self.stats.get("current_balance", PAPER_BALANCE)
                logger.info(f"Loaded {len(self.trades)} existing trades, balance: ${self.balance:.2f}")
            except Exception as e:
                logger.warning(f"Failed to load trades: {e}")

        if STATS_FILE.exists():
            try:
                self.stats = json.loads(STATS_FILE.read_text())
            except Exception as e:
                logger.warning(f"Failed to load stats: {e}")

    def save(self):
        """Persist trades and stats to disk."""
        self.stats["current_balance"] = self.balance
        self.stats["total_trades"] = len(self.trades)
        self.stats["pending_trades"] = sum(1 for t in self.trades if t.get("status") == "open")
        self.stats["win_rate"] = self.stats["winning_trades"] / max(1, self.stats["winning_trades"] + self.stats["losing_trades"])
        self.stats["total_pnl"] = sum(t.get("pnl", 0) for t in self.trades)
        self.stats["avg_pnl"] = self.stats["total_pnl"] / max(1, len(self.trades))

        trades_data = {"trades": self.trades, "stats": self.stats}
        TRADES_FILE.write_text(json.dumps(trades_data, indent=2))
        STATS_FILE.write_text(json.dumps(self.stats, indent=2))

    def can_bet(self, amount: float) -> bool:
        """Check if we have sufficient balance for a bet."""
        return self.balance >= amount and amount >= MIN_BET

    def place_bet(self, ticker: str, direction: str, price: float,
                  amount: float, market_info: Dict, forecast: Dict) -> Optional[Dict]:
        """
        Place a paper trade bet.
        direction: 'over' (buy YES) or 'under' (buy YES on under market)
        price: probability price
        amount: dollar amount to risk

        Returns trade record or None if insufficient balance.
        """
        if not self.can_bet(amount):
            logger.warning(f"Insufficient balance ${self.balance:.2f} for ${amount:.2f} bet")
            return None

        cost = price * amount  # Cost to buy YES position
        if cost > self.balance:
            logger.warning(f"Bet cost ${cost:.2f} exceeds balance ${self.balance:.2f}")
            return None

        self.balance -= cost

        trade = {
            "id": len(self.trades) + 1,
            "ticker": ticker,
            "direction": direction,
            "price": price,
            "amount": amount,
            "cost": cost,
            "market_question": market_info.get("question", ""),
            "threshold": market_info.get("threshold"),
            "city_key": market_info.get("city_key"),
            "city_name": forecast.get("city_name"),
            "forecast_high": forecast.get("today_high"),
            "forecast_tomorrow_high": forecast.get("tomorrow_high"),
            "edge": market_info.get("edge", 0),
            "status": "open",
            "pnl": 0.0,
            "opened_at": datetime.utcnow().isoformat(),
            "closed_at": None,
            "settlement_price": None,
            "actual_outcome": None
        }

        self.trades.append(trade)
        self.save()

        logger.info(f"PAPER BET: {direction.upper()} {amount:.2f} on {ticker} @ {price:.2f} "
                   f"(forecast: {forecast.get('today_high')}°F, threshold: {market_info.get('threshold')}°F, "
                   f"edge: {market_info.get('edge', 0):+.1f}°F)")

        return trade

    def resolve_trade(self, ticker: str, actual_outcome: bool, settlement_price: float):
        """
        Resolve a settled trade.
        actual_outcome: True if the event happened (YES won), False otherwise
        settlement_price: the final YES price
        """
        for trade in self.trades:
            if trade["ticker"] == ticker and trade["status"] == "open":
                trade["status"] = "settled"
                trade["closed_at"] = datetime.utcnow().isoformat()
                trade["settlement_price"] = settlement_price
                trade["actual_outcome"] = actual_outcome

                if actual_outcome:
                    # Won: get back amount (even money on binary)
                    payout = trade["amount"]  # Binary pays 1:1 on YES
                    net_payout = payout * 0.984  # 1.6% Kalshi fee on winnings
                    self.balance += net_payout
                    trade["pnl"] = net_payout - trade["cost"]
                    trade["gross_pnl"] = payout - trade["cost"]
                    trade["fee_paid"] = payout - net_payout
                    self.stats["winning_trades"] += 1
                    logger.info(f"PAPER WIN: {ticker} - Gross ${trade['gross_pnl']:.2f}, Fee ${trade['fee_paid']:.3f}, Net ${trade['pnl']:.2f}, Balance: ${self.balance:.2f}")
                else:
                    # Lost
                    trade["pnl"] = -trade["cost"]
                    trade["gross_pnl"] = -trade["cost"]
                    trade["fee_paid"] = 0.0
                    self.stats["losing_trades"] += 1
                    logger.info(f"PAPER LOSS: {ticker} - Lost ${trade['cost']:.2f}, Balance: ${self.balance:.2f}")

                self.save()
                return

        logger.warning(f"Could not find open trade for {ticker} to resolve")

    def get_open_trades(self) -> List[Dict]:
        """Get all open (unsettled) trades."""
        return [t for t in self.trades if t["status"] == "open"]

    def get_summary(self) -> Dict:
        """Get trading summary."""
        return {
            "balance": self.balance,
            "total_trades": len(self.trades),
            "open_trades": len(self.get_open_trades()),
            "settled_trades": len([t for t in self.trades if t["status"] == "settled"]),
            "winning_trades": self.stats.get("winning_trades", 0),
            "losing_trades": self.stats.get("losing_trades", 0),
            "win_rate": self.stats.get("win_rate", 0.0),
            "total_pnl": self.stats.get("total_pnl", 0.0),
        }


# =============================================================================
# THERMOSTAT MAIN BOT
# =============================================================================

class ThermostatBot:
    """
    Weather forecast arbitrage bot for Kalshi climate markets.

    Core loop:
    1. Fetch NOAA forecasts for key cities (~every 30 min)
    2. Poll Kalshi for climate markets (smart timing: aggressive around 14:00 UTC)
    3. When a market matches a city we have forecasts for:
       - Compare NOAA projection vs market threshold
       - If edge exists (NOAA significantly different from line), bet
    4. Track open positions and resolve when markets close
    """
    
    def __init__(self):
        self.api = KalshiAPI()
        self.noaa = NOAAClient()
        self.parser = ClimateMarketParser()
        self.ledger = PaperLedger()
        self.forecasts: Dict[str, Dict] = {}
        self.running = True
        self.last_forecast_refresh = 0
        
        # Build city_key -> series ticker mapping
        self.city_series: Dict[str, str] = {}
        for city_key, city_cfg in CITIES.items():
            series = city_cfg.get("kalshi_series")
            if series:
                self.city_series[city_key] = series
        
        # Signal handling for graceful shutdown
        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)
    
    def _shutdown(self, signum, frame):
        """Graceful shutdown."""
        logger.info("Shutting down Thermostat...")
        self.running = False
    
    def _get_poll_interval(self) -> int:
        """Smart polling: 5 min during 13:30-15:00 UTC, 30 min otherwise."""
        hour_utc = datetime.utcnow().hour
        if AGGRESSIVE_POLL_START <= hour_utc < AGGRESSIVE_POLL_END:
            return AGGRESSIVE_INTERVAL
        return NORMAL_INTERVAL
    
    def initialize(self):
        """Initialize bot: fetch forecasts and log configuration."""
        logger.info("=" * 60)
        logger.info("THERMOSTAT - Weather Forecast Arbitrage Bot")
        logger.info("=" * 60)
        logger.info(f"Cities tracked: {list(self.city_series.keys())}")
        logger.info(f"Series mapping: {self.city_series}")
        logger.info(f"Smart polling: aggressive {AGGRESSIVE_INTERVAL}s ({AGGRESSIVE_POLL_START}:00-{AGGRESSIVE_POLL_END}:00 UTC), "
                   f"normal {NORMAL_INTERVAL}s otherwise")
        logger.info(f"Markets open at 14:00 UTC daily (10 AM ET)")
        
        # Initial forecast fetch
        self.refresh_forecasts()
        
        logger.info(f"Initial balance: ${self.ledger.balance:.2f}")
        logger.info(f"Paper mode: {PAPER_MODE}")
    
    def refresh_forecasts(self):
        """Fetch latest NOAA forecasts for all cities."""
        logger.info("Fetching NOAA forecasts...")
        self.forecasts = self.noaa.get_all_forecasts()
        self.last_forecast_refresh = time.time()
        return self.forecasts
    
    def scan_markets(self) -> List[Dict]:
        """
        Scan Kalshi for climate markets across all city series.
        Fetches full market data from API for accurate parsing.
        Returns list of trading opportunities.
        """
        opportunities = []
        
        for city_key, series_ticker in self.city_series.items():
            markets = self.api.get_open_markets(series_ticker)
            
            for market in markets:
                # Fetch full market details from API
                full_market = self.api._get(f'/markets/{market.ticker}')
                if 'market' not in full_market:
                    continue
                
                market_data = full_market['market']
                parsed = self.parser.parse_market_api(market_data)
                if not parsed:
                    continue
                
                # Get forecast for this city
                forecast = self.forecasts.get(city_key)
                if not forecast:
                    continue
                
                # Use tomorrow's high for next-day markets, today's for same-day
                forecast_high = forecast.get("tomorrow_high") or forecast.get("today_high")
                if forecast_high is None:
                    continue
                
                direction = parsed["direction"]
                effective_low = parsed.get("effective_low", 0)
                effective_high = parsed.get("effective_high", 999)
                threshold = parsed.get("threshold", 0)
                yes_bid = parsed.get("yes_bid", 0)
                yes_ask = parsed.get("yes_ask", 1)
                mid_price = (yes_bid + yes_ask) / 2
                action = None  # Initialize to avoid UnboundLocalError
                
                # Calculate edge based on direction
                if direction == "over":
                    # Market pays YES if temp > threshold+1°F
                    # Edge = forecast_high - (threshold + 1)
                    edge = forecast_high - (threshold + 1)
                    if edge > 2 and mid_price < 0.95:
                        action = "over"
                elif direction == "under":
                    # Market pays YES if temp < threshold-1°F
                    # Edge = (threshold - 1) - forecast_high
                    edge = (threshold - 1) - forecast_high
                    if edge > 2 and mid_price < 0.95:
                        action = "under"
                elif direction == "range":
                    # Between range: pays YES if temp in [threshold, threshold+1]
                    # Check if forecast falls in the range
                    if threshold <= forecast_high <= threshold + 1:
                        # NOAA says in range - this is good for BETWEEN markets
                        # But check price vs probability
                        implied_prob = mid_price
                        if implied_prob < 0.85:  # Market undervaluing the range
                            edge = 5  # Treat as strong signal
                            action = "range"
                    else:
                        edge = 0
                else:
                    continue
                
                if action:
                    opportunity = {
                        "market_ticker": market.ticker,
                        "market_data": parsed,
                        "forecast": forecast,
                        "forecast_high": forecast_high,
                        "threshold": threshold,
                        "effective_range": (effective_low, effective_high),
                        "edge": edge,
                        "action": action,
                        "price": mid_price,
                        "city_key": city_key,
                    }
                    opportunities.append(opportunity)
                    logger.info(f"OPP: {action.upper()} {market.ticker} | "
                               f"City: {city_key} | Forecast: {forecast_high}°F | "
                               f"Range: [{effective_low:.0f}, {effective_high:.0f}]°F | "
                               f"Edge: {edge:+.1f}°F | Price: ${mid_price:.2f}")
        
        return opportunities
    
    def place_bets(self, opportunities: List[Dict]):
        """Place paper bets on identified opportunities."""
        for opp in opportunities:
            ticker = opp["market_ticker"]
            
            # Check if we already have a position
            open_trades = self.ledger.get_open_trades()
            if any(t["ticker"] == ticker for t in open_trades):
                continue
            
            # Determine bet amount (scaled by edge)
            edge = abs(opp["edge"])
            if edge >= 5:
                amount = MAX_BET
            elif edge >= 3:
                amount = MAX_BET * 0.75
            else:
                amount = MAX_BET * 0.5
            
            amount = round(amount, 2)
            
            market_info = {
                "question": opp["market_data"].get("question", ""),
                "threshold": opp["threshold"],
                "city_key": opp["city_key"],
                "edge": opp["edge"],
                "effective_range": opp["effective_range"],
            }
            
            self.ledger.place_bet(
                ticker=ticker,
                direction=opp["action"],
                price=opp["price"],
                amount=amount,
                market_info=market_info,
                forecast=opp["forecast"]
            )
    
    def check_positions(self):
        """Check and resolve any positions that have settled."""
        open_trades = self.ledger.get_open_trades()
        if not open_trades:
            return
        
        now = datetime.utcnow()
        
        for trade in open_trades:
            ticker = trade["ticker"]
            
            # Get current market status
            result = self.api._get(f'/markets/{ticker}')
            if 'market' not in result:
                # Market might have closed
                logger.info(f"Market {ticker} not found in API - may be settled")
                continue
            
            market = result['market']
            status = market.get('status', '')
            close_time = market.get('close_time', '')
            
            # Check if market has closed
            if status != 'active' or close_time:
                try:
                    close_dt = datetime.fromisoformat(close_time.replace('Z', '+00:00'))
                    if close_dt < datetime.now(close_dt.tzinfo):
                        logger.info(f"Market {ticker} has closed, would need settlement resolution")
                        # In production, fetch settlement price from API
                except:
                    pass
        
        # Refresh forecasts every 30 minutes
        if time.time() - self.last_forecast_refresh > 1800:
            self.refresh_forecasts()
    
    def run_once(self):
        """Execute one iteration of the trading loop."""
        now = datetime.utcnow()
        interval = self._get_poll_interval()
        mode = "AGGRESSIVE" if interval == AGGRESSIVE_INTERVAL else "normal"
        
        logger.info(f"[{now.strftime('%H:%M:%S UTC')}] Climate scan ({mode} poll)...")
        
        # Refresh forecasts every 30 min
        if time.time() - self.last_forecast_refresh > 1800:
            self.refresh_forecasts()
        
        # Scan for opportunities
        opportunities = self.scan_markets()
        
        if opportunities:
            logger.info(f"Found {len(opportunities)} trading opportunities")
            self.place_bets(opportunities)
        
        # Check existing positions
        self.check_positions()
        
        # Log current status
        summary = self.ledger.get_summary()
        logger.info(f"Status: Balance ${summary['balance']:.2f} | "
                   f"Trades: {summary['total_trades']} ({summary['open_trades']} open) | "
                   f"Win Rate: {summary['win_rate']:.1%} | PnL: ${summary['total_pnl']:.2f}")
        
        return opportunities
    
    def run(self):
        """Main loop with smart polling."""
        self.initialize()
        
        while self.running:
            try:
                interval = self._get_poll_interval()
                self.run_once()
            except Exception as e:
                logger.error(f"Error in main loop: {e}", exc_info=True)
                interval = NORMAL_INTERVAL
            
            # Sleep with interruptible polling
            logger.info(f"Sleeping {interval}s until next scan...")
            for _ in range(interval):
                if not self.running:
                    break
                time.sleep(1)
        
        logger.info("Thermostat stopped.")


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    bot = ThermostatBot()
    bot.run()
