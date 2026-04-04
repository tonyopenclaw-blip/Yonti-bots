# config.py - Thermostat Configuration
# Weather forecast arbitrage for Kalshi climate markets

import os
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "thermostat.log"
TRADES_FILE = DATA_DIR / "thermostat_trades.json"
STATS_FILE = DATA_DIR / "thermostat_stats.json"

DATA_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

# =============================================================================
# KALSHI API CONFIG
# =============================================================================
KALSHI_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
KALSHI_ACCESS_KEY = os.getenv("KALSHI_ACCESS_KEY", "c5187b0e-785e-4749-b45b-70f9cd40bb0f")

# =============================================================================
# PAPER TRADING CONFIG
# =============================================================================
PAPER_MODE = True
PAPER_BALANCE = 100.00
MAX_BET = 2.00
MIN_BET = 0.10

# =============================================================================
# NOAA/NWS WEATHER API CONFIG
# =============================================================================
NOAA_BASE_URL = "https://api.weather.gov"
POLL_INTERVAL_SEC = 3600  # Poll every hour for new markets

# Key cities for weather forecasting
# Each city has: (name, lat, lon, kalshi_series ticker for daily high temp markets)
CITIES = {
    "NYC": {
        "name": "New York City",
        "lat": 40.7128,
        "lon": -74.0060,
        "kalshi_series": "KXHIGHNY",
        "tz": "America/New_York",
    },
    "PHX": {
        "name": "Phoenix",
        "lat": 33.4484,
        "lon": -112.0740,
        "kalshi_series": "KXHIGHTPHX",
        "tz": "America/Phoenix",
    },
    "CHI": {
        "name": "Chicago",
        "lat": 41.8781,
        "lon": -87.6298,
        "kalshi_series": "KXHIGHCHI",
        "tz": "America/Chicago",
    },
    "HOU": {
        "name": "Houston",
        "lat": 29.7604,
        "lon": -95.3698,
        "kalshi_series": "KXHIGHTHOU",
        "tz": "America/Chicago",
    },
    "ATL": {
        "name": "Atlanta",
        "lat": 33.7490,
        "lon": -84.3880,
        "kalshi_series": "KXHIGHTATL",
        "tz": "America/New_York",
    },
    "LAX": {
        "name": "Los Angeles",
        "lat": 34.0522,
        "lon": -118.2437,
        "kalshi_series": "KXHIGHLAX",
        "tz": "America/Los_Angeles",
    },
    "DEN": {
        "name": "Denver",
        "lat": 39.7392,
        "lon": -104.9903,
        "kalshi_series": "KXHIGHTDEN",
        "tz": "America/Denver",
    },
    "PHL": {
        "name": "Philadelphia",
        "lat": 39.9526,
        "lon": -75.1652,
        "kalshi_series": "KXHIGHTPHL",
        "tz": "America/New_York",
    },
    "SAT": {
        "name": "San Antonio",
        "lat": 29.4241,
        "lon": -98.4936,
        "kalshi_series": "KXHIGHTSATX",
        "tz": "America/Chicago",
    },
    "SD": {
        "name": "San Diego",
        "lat": 32.7157,
        "lon": -117.1611,
        "kalshi_series": "KXHIGHTSD",
        "tz": "America/Los_Angeles",
    },
}

# Market timing (all times in UTC):
#   Markets open: 14:00 UTC (10 AM ET) = ~22:00-23:00 local for most cities
#   Markets close: 05:00-07:00 UTC next day (midnight-2 AM local)
#   Trading window: ~39-41 hours per market
#   
# Aggressive polling window: 13:30-15:30 UTC daily (30 min before/after market opens)
AGGRESSIVE_POLL_START = 13   # UTC hour - start aggressive polling
AGGRESSIVE_POLL_END = 15     # UTC hour - end aggressive polling
AGGRESSIVE_INTERVAL = 300    # 5 minutes during aggressive window
NORMAL_INTERVAL = 1800      # 30 minutes during normal times

# All known climate series tickers for auto-discovery
CLIMATE_SERIES_PATTERNS = [
    "KXHIGHNY", "KXHIGHTNYC", "KXHIGHCHI", "KXHIGHTPHX", "KXHIGHTHOU",
    "KXHIGHTATL", "KXHIGHLAX", "KXHIGHTDEN", "KXHIGHTPHL", "KXHIGHTSATX",
    "KXHIGHMIA", "KXHIGHTSEA", "KXHIGHTBOS", "KXHIGHTLV", "KXHIGHTDAL",
    "KXLOWNYC", "KXLOWTNYC", "KXLOWCHI", "KXLOWTHOU", "KXLOWTAUS",
]

# =============================================================================
# LOGGING
# =============================================================================
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
