#!/usr/bin/env python3
"""
The Odds API Client for Uncle Vito
Fetches real DK/FD odds for NBA, NHL, NCAAB
"""

import requests
from typing import Dict, List, Optional
from config import ODDS_API_KEY, ODDS_API_BASE, ODDS_REGIONS, ODDS_SPORTS

class OddsAPIClient:
    """Client for The Odds API - real DraftKings/FanDuel odds."""

    def __init__(self):
        self.api_key = ODDS_API_KEY
        self.base_url = ODDS_API_BASE
        self.region = ODDS_REGIONS  # 'us' for DK/FD
        self.bookmakers = ["draftkings", "fanduel"]  # Specific books we want

    def get_odds(self, sport_key: str, markets: List[str] = None) -> List[Dict]:
        """
        Fetch odds for a sport.
        sport_key: 'basketball_nba', 'icehockey_nhl', 'basketball_ncaab'
        markets: ['h2h', 'spreads', 'totals'] (h2h = moneyline)
        """
        if markets is None:
            markets = ["h2h", "spreads", "totals"]

        url = f"{self.base_url}/sports/{sport_key}/odds"
        
        params = {
            "api_key": self.api_key,
            "regions": self.region,
            "markets": ",".join(markets),
            "oddsFormat": "american",
        }

        try:
            response = requests.get(url, params=params, timeout=15)
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 429:
                print("Rate limited by Odds API")
                return []
            else:
                print(f"Odds API error: {response.status_code}")
                return []
        except Exception as e:
            print(f"Odds API fetch error: {e}")
            return []

    def get_best_odds(self, sport_key: str) -> Dict[str, Dict]:
        """
        Get the best available odds for each market.
        Returns dict with game info and best DK/FD odds.
        """
        data = self.get_odds(sport_key)
        results = {}

        for event in data:
            game_id = event.get("id", "")
            home_team = event.get("home_team", "")
            away_team = event.get("away_team", "")
            commence_time = event.get("commence_time", "")

            # Get best odds from available bookmakers
            bookmakers = event.get("bookmakers", [])
            
            game_odds = {
                "game_id": game_id,
                "home_team": home_team,
                "away_team": away_team,
                "commence_time": commence_time,
                "markets": {}
            }

            for bookmaker in bookmakers:
                book_name = bookmaker.get("key", "")
                if book_name not in self.bookmakers:
                    continue

                for market in bookmaker.get("markets", []):
                    market_key = market.get("key", "")
                    outcomes = market.get("outcomes", [])

                    if market_key not in game_odds["markets"]:
                        game_odds["markets"][market_key] = {}

                    for outcome in outcomes:
                        name = outcome.get("name", "")
                        price = outcome.get("price", 0)
                        point = outcome.get("point", None)

                        game_odds["markets"][market_key][name] = {
                            "odds": price,
                            "point": point,
                            "bookmaker": book_name
                        }

            if game_odds["markets"]:
                results[game_id] = game_odds

        return results

    def get_moneyline(self, sport_key: str) -> List[Dict]:
        """Get moneyline odds only."""
        return self.get_odds(sport_key, markets=["h2h"])

    def get_spreads(self, sport_key: str) -> List[Dict]:
        """Get point spread odds."""
        return self.get_odds(sport_key, markets=["spreads"])

    def get_totals(self, sport_key: str) -> List[Dict]:
        """Get totals (over/under) odds."""
        return self.get_odds(sport_key, markets=["totals"])


if __name__ == "__main__":
    client = OddsAPIClient()
    
    # Test with NBA
    print("Fetching NBA odds...")
    nba_odds = client.get_best_odds(ODDS_SPORTS["nba"])
    print(f"Found {len(nba_odds)} games with odds")
    
    # Test with NHL
    print("\nFetching NHL odds...")
    nhl_odds = client.get_best_odds(ODDS_SPORTS["nhl"])
    print(f"Found {len(nhl_odds)} games with odds")
