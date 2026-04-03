#!/usr/bin/env python3
"""
Uncle Vito's Betting Report Generator 🍝
Fetches sports data from ESPN API and generates daily betting reports.
"""

import json
import math
import random
import logging
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any, Set
from dataclasses import dataclass
import config

try:
    import requests
except ImportError:
    requests = None

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("uncle_vito")


@dataclass
class Team:
    """Represents a team in a game."""
    id: str
    name: str
    abbreviation: str
    logo: str
    record: str = ""
    seed: int = 0


@dataclass
class Player:
    """Represents a player for props."""
    id: str
    name: str
    team: str
    position: str = ""
    stat_proj: float = 0.0


@dataclass
class Game:
    """Represents a sporting event."""
    id: str
    name: str
    sport: str
    date: str
    time: str
    venue: str
    home_team: Team
    away_team: Team
    home_score: int = 0
    away_score: int = 0
    status: str = "scheduled"  # scheduled, live, final


@dataclass
class PropPick:
    """A player prop selection."""
    player: str
    team: str
    stat_type: str
    line: float
    direction: str  # "over" or "under"
    odds: int
    source_signal: str = ""
    confidence: int = 70
    rest_day: bool = False  # Track if player is a rest day (not in DK slate)


@dataclass
class WinnerPick:
    """A game winner selection."""
    team: str
    opponent: str
    pick_type: str  # "moneyline" or "spread"
    line: float
    odds: int
    source_signal: str = ""
    confidence: int = 70


class SourceSignals:
    """
    Simulates source signal aggregation from betting sources.
    In production, this would integrate with actual source feeds.
    """

    def __init__(self):
        self.sources = config.SOURCES

    def get_signal(self, sport: str, pick_type: str, teams: List[str] = None) -> Dict[str, Any]:
        """
        Get aggregated signal from sources.
        Returns direction and confidence boost.
        """
        total_weight = 0
        weighted_direction = 0
        confidence_boost = 0

        for source_key, source in self.sources.items():
            # Simulate source picks (in production, fetch from actual sources)
            signal = self._simulate_source_signal(source_key, sport, pick_type, teams)
            weighted_direction += signal["direction"] * source["weight"]
            confidence_boost += source["confidence_boost"] * source["weight"]
            total_weight += source["weight"]

        # Normalize
        if total_weight > 0:
            weighted_direction /= total_weight
            confidence_boost /= total_weight

        direction = "over" if weighted_direction > 0 else "under"
        base_confidence = 65
        final_confidence = min(95, int(base_confidence + confidence_boost))

        return {
            "direction": direction,
            "confidence": final_confidence,
            "signal_strength": abs(weighted_direction)
        }

    def _simulate_source_signal(self, source_key: str, sport: str, pick_type: str, teams: List[str] = None) -> Dict[str, Any]:
        """
        Simulate a betting source's signal.
        Uses deterministic randomness based on source + sport for consistency.
        """
        seed = hash(f"{source_key}_{sport}_{pick_type}_{teams}") % 1000
        random.seed(seed)

        # Sources tend to lean a certain direction (70% lean, 30% contrarian)
        direction = 1 if random.random() > 0.3 else -1
        strength = random.uniform(0.5, 1.0)

        return {
            "direction": direction * strength,
            "confidence": random.randint(60, 85)
        }

    def get_source_pick_summary(self) -> str:
        """Return a formatted summary of source activity."""
        summaries = []
        for source_key, source in self.sources.items():
            summaries.append(f"**{source['name']}** ({int(source['weight']*100)}%)")
        return ", ".join(summaries)


class DraftKingsClient:
    """
    Client for fetching DraftKings DFS player availability and salaries.
    Cross-references with hardcoded player maps to identify rest days.
    """
    
    # DK API endpoints
    DK_SPORTS_URL = "https://api.draftkings.com/sites/US-DK/sports/v1/sports"
    DK_DRAFTABLES_URL = "https://api.draftkings.com/draftgroups/v1/draftgroups/{draft_group_id}/draftables"
    
    # Sport to DK sport key mapping
    DK_SPORT_KEYS = {
        "NBA": "NBA",
        "NHL": "NHL", 
        "MLB": "MLB",
    }
    
    def __init__(self):
        self._active_players: Dict[str, Set[str]] = {}  # sport -> set of player names
        self._draft_groups: Dict[str, str] = {}  # sport -> draft_group_id
        self._last_fetch: Dict[str, datetime] = {}  # sport -> last fetch time
        self._cache_duration = timedelta(minutes=15)  # Cache for 15 minutes
        self._fetch_failed = False
        
    def _get_headers(self) -> Dict[str, str]:
        """Get headers needed for DK API requests."""
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://www.draftkings.com",
            "Referer": "https://www.draftkings.com/",
        }
    
    def _fetch_json(self, url: str) -> Optional[Dict]:
        """Fetch JSON from URL with error handling."""
        if not requests:
            logger.warning("requests library not available, DK API unavailable")
            self._fetch_failed = True
            return None
            
        try:
            response = requests.get(url, headers=self._get_headers(), timeout=10)
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 403:
                logger.warning("DK API access denied (403) - server-side calls blocked by Akamai")
                self._fetch_failed = True
                return None
            else:
                logger.warning(f"DK API returned status {response.status_code}")
                return None
        except Exception as e:
            logger.warning(f"DK API fetch failed: {e}")
            self._fetch_failed = True
            return None
    
    def _get_sport_key_for_dk(self, sport: str) -> Optional[str]:
        """Get the DK sport key for a given sport."""
        return self.DK_SPORT_KEYS.get(sport)
    
    def fetch_draft_groups(self, sport: str) -> Optional[str]:
        """
        Fetch active draft group ID for a sport.
        Returns the draft_group_id or None if unavailable.
        """
        # Check cache first
        if sport in self._draft_groups:
            last_fetch = self._last_fetch.get(sport)
            if last_fetch and datetime.now() - last_fetch < self._cache_duration:
                return self._draft_groups[sport]
        
        # Fetch sports list to find draft group
        data = self._fetch_json(self.DK_SPORTS_URL)
        if not data:
            return None
            
        try:
            sports = data.get("sports", [])
            dk_sport_key = self._get_sport_key_for_dk(sport)
            
            for sport_data in sports:
                if sport_data.get("name") == dk_sport_key or sport_data.get(" abbreviation") == dk_sport_key:
                    # Look for active draft group
                    for category in sport_data.get("categories", []):
                        for contest in category.get("contests", []):
                            draft_group_id = contest.get("draftGroupId")
                            if draft_group_id:
                                self._draft_groups[sport] = draft_group_id
                                self._last_fetch[sport] = datetime.now()
                                logger.info(f"Found DK draft group for {sport}: {draft_group_id}")
                                return draft_group_id
        except Exception as e:
            logger.warning(f"Error parsing DK sports response: {e}")
            return None
            
        return None
    
    def fetch_draftables(self, sport: str) -> List[Dict]:
        """
        Fetch draftable players (with salaries) for a sport's current slate.
        Returns list of player dicts with name, team, salary, position.
        """
        draft_group_id = self.fetch_draft_groups(sport)
        if not draft_group_id:
            return []
            
        url = self.DK_DRAFTABLES_URL.format(draft_group_id=draft_group_id)
        data = self._fetch_json(url)
        
        if not data:
            return []
            
        draftables = []
        try:
            for draftable in data.get("draftables", []):
                player_info = draftable.get("player", {})
                player_name = player_info.get("fullName", "")
                if not player_name:
                    continue
                    
                team = player_info.get("teamAbbreviation", "")
                salary = draftable.get("salary", 0)
                position = draftable.get("position", "")
                
                draftables.append({
                    "name": player_name,
                    "team": team,
                    "salary": salary,
                    "position": position,
                    "player_id": player_info.get("id", ""),
                })
                
            logger.info(f"Fetched {len(draftables)} draftables from DK for {sport}")
        except Exception as e:
            logger.warning(f"Error parsing DK draftables response: {e}")
            return []
            
        return draftables
    
    def fetch_active_players(self, sport: str) -> Set[str]:
        """
        Fetch the set of active (draftable) player names for a sport.
        Uses caching to avoid repeated API calls.
        """
        # Check cache first
        if sport in self._active_players:
            last_fetch = self._last_fetch.get(sport)
            if last_fetch and datetime.now() - last_fetch < self._cache_duration:
                # Cache hit - but if cached set is empty, the API previously failed
                if not self._active_players[sport]:
                    self._fetch_failed = True  # API failed, mark it
                return self._active_players[sport]
        
        # Fetch fresh data
        draftables = self.fetch_draftables(sport)
        player_names = {d["name"] for d in draftables}
        
        self._active_players[sport] = player_names
        self._last_fetch[sport] = datetime.now()
        
        return player_names
    
    def is_player_active_dk(self, player_name: str, team_abbrev: str, sport: str) -> bool:
        """
        Check if a player is active in the current DK DFS slate.
        
        Args:
            player_name: Full name of the player
            team_abbrev: Team abbreviation (e.g., "PHI", "LAL")
            sport: Sport (NBA, NHL, MLB)
            
        Returns:
            True if player is in the DK slate, False otherwise
        """
        # If DK API failed, we can't verify - assume player is OUT (conservative)
        # "If they're not in DK DFS, they can't be in any parlay"
        if self._fetch_failed:
            return False
            
        active_players = self.fetch_active_players(sport)
        
        # Direct name match
        if player_name in active_players:
            return True
            
        # Try partial name matching (first + last name)
        name_parts = player_name.lower().split()
        if len(name_parts) >= 2:
            first, last = name_parts[0], name_parts[-1]
            for active_name in active_players:
                active_parts = active_name.lower().split()
                if len(active_parts) >= 2 and active_parts[0] == first and active_parts[-1] == last:
                    return True
                    
        return False
    
    def get_rest_day_players(self, hardcoded_players: List[tuple], team_abbr: str, sport: str) -> List[tuple]:
        """
        Filter hardcoded players and return those NOT in DK slate (rest days).
        
        Args:
            hardcoded_players: List of (player_name, stat_type, line) tuples
            team_abbr: Team abbreviation
            sport: Sport (NBA, NHL, MLB)
            
        Returns:
            List of players that are NOT in the DK slate (probable rest days)
        """
        rest_day_players = []
        active_players = self.fetch_active_players(sport)
        
        for player_name, stat_type, line in hardcoded_players:
            if player_name not in active_players:
                # Try partial matching
                name_parts = player_name.lower().split()
                if len(name_parts) >= 2:
                    first, last = name_parts[0], name_parts[-1]
                    found = False
                    for active_name in active_players:
                        active_parts = active_name.lower().split()
                        if len(active_parts) >= 2 and active_parts[0] == first and active_parts[-1] == last:
                            found = True
                            break
                    if not found:
                        rest_day_players.append((player_name, stat_type, line))
                else:
                    rest_day_players.append((player_name, stat_type, line))
                    
        return rest_day_players


class OddsCalculator:
    """Handles odds calculations for parlays."""

    @staticmethod
    def american_to_decimal(odds: int) -> float:
        """Convert American odds to decimal."""
        if odds > 0:
            return 1 + (odds / 100)
        else:
            return 1 + (100 / abs(odds))

    @staticmethod
    def decimal_to_american(decimal: float) -> int:
        """Convert decimal odds to American."""
        if decimal >= 2.0:
            return int((decimal - 1) * 100)
        else:
            return int(-100 / (decimal - 1))

    @staticmethod
    def calculate_parlay_odds(picks: List[Dict], vig: int = -110) -> Dict[str, Any]:
        """
        Calculate parlay odds from list of picks.
        Standard 4-leg parlay with standard -110 juice per leg.
        """
        legs = len(picks)
        if legs == 0:
            return {"odds": 0, "payout": 0, "implied_prob": 0}

        # Use actual odds if provided, otherwise default vig
        total_odds = 1.0
        for pick in picks:
            pick_odds = pick.get("odds", vig)
            total_odds *= OddsCalculator.american_to_decimal(pick_odds)

        # Apply parlay multiplier (roughly +350 per leg at standard juice)
        # 4-leg at -110 each = ~+1228
        american_odds = OddsCalculator.decimal_to_american(total_odds)

        # Calculate implied probability
        prob = 1 / total_odds

        return {
            "odds": american_odds,
            "payout": american_odds,
            "implied_prob": round(prob * 100, 1)
        }

    @staticmethod
    def get_default_odds(favorite: bool = True, sport: str = "nba") -> int:
        """Get default odds based on favorite/underdog status."""
        sport_odds = config.DEFAULT_ML_ODDS.get(sport, config.DEFAULT_ML_ODDS["nba"])
        return sport_odds["favorite"] if favorite else sport_odds["underdog"]


class ESPNClient:
    """Client for fetching data from ESPN API."""

    def __init__(self):
        self.base_url = "https://site.api.espn.com/apis/site/v2"

    def fetch_scoreboard(self, sport: str, date: str = None) -> Dict[str, Any]:
        """
        Fetch scoreboard for a sport on a given date.
        Date format: YYYYMMDD
        """
        if date is None:
            date = datetime.now().strftime("%Y%m%d")

        sport_map = {
            "NBA": ("basketball", "nba"),
            "NHL": ("hockey", "nhl"),
            "MLB": ("baseball", "mlb"),
        }

        if sport not in sport_map:
            raise ValueError(f"Unknown sport: {sport}")

        league, slug = sport_map[sport]
        url = f"{self.base_url}/sports/{league}/{slug}/scoreboard"

        if requests:
            try:
                response = requests.get(url, params={"dates": date}, timeout=10)
                response.raise_for_status()
                return response.json()
            except Exception as e:
                print(f"API fetch error for {sport}: {e}")
                return {"events": []}
        else:
            # Fallback: use web_fetch simulation
            return {"events": []}

    def parse_games(self, data: Dict[str, Any], sport: str) -> List[Game]:
        """Parse ESPN scoreboard data into Game objects."""
        games = []

        for event in data.get("events", []):
            try:
                comp = event.get("competitions", [{}])[0]
                competitors = comp.get("competitors", [])

                home_data = next((c for c in competitors if c.get("homeAway") == "home"), None)
                away_data = next((c for c in competitors if c.get("homeAway") == "away"), None)

                if not home_data or not away_data:
                    continue

                home_team = Team(
                    id=home_data["team"]["id"],
                    name=home_data["team"]["displayName"],
                    abbreviation=home_data["team"]["abbreviation"],
                    logo=home_data["team"].get("logo", ""),
                    record=home_data.get("records", [""])[0].get("summary", ""),
                )

                away_team = Team(
                    id=away_data["team"]["id"],
                    name=away_data["team"]["displayName"],
                    abbreviation=away_data["team"]["abbreviation"],
                    logo=away_data["team"].get("logo", ""),
                    record=away_data.get("records", [""])[0].get("summary", ""),
                )

                # Parse date/time
                date_str = event.get("date", "")
                try:
                    dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    time_str = dt.strftime("%I:%M %p ET")
                except:
                    time_str = "TBD"

                # Status
                status = "scheduled"
                if event.get("status", {}).get("type", {}).get("state") == "in":
                    status = "live"
                elif event.get("status", {}).get("type", {}).get("state") == "post":
                    status = "final"

                game = Game(
                    id=event["id"],
                    name=event.get("name", f"{away_team.abbreviation} @ {home_team.abbreviation}"),
                    sport=sport,
                    date=date_str[:10],
                    time=time_str,
                    venue=comp.get("venue", {}).get("fullName", ""),
                    home_team=home_team,
                    away_team=away_team,
                    status=status,
                )

                games.append(game)

            except Exception as e:
                print(f"Error parsing event: {e}")
                continue

        return games


class UncleVitoReport:
    """
    Uncle Vito's Betting Report Generator.
    Builds daily sports betting reports with props and winners parlays.
    """

    def __init__(self):
        self.espn = ESPNClient()
        self.sources = SourceSignals()
        self.odds = OddsCalculator()
        self.dk = DraftKingsClient()  # DraftKings DFS client for player availability
        self.games: Dict[str, List[Game]] = {}
        self.prop_picks: List[PropPick] = []
        self.winner_picks: List[WinnerPick] = []
        self._rest_day_warnings: Dict[str, List[str]] = {}  # sport -> list of warning messages

    def fetch_todays_games(self) -> Dict[str, List[Game]]:
        """Fetch today's games across all configured sports."""
        today = datetime.now().strftime("%Y%m%d")

        for sport in config.SPORTS:
            data = self.espn.fetch_scoreboard(sport, today)
            self.games[sport] = self.espn.parse_games(data, sport)

        return self.games

    def generate_props_parlay(self, sport: str, num_legs: int = 3) -> List[PropPick]:
        """
        Generate a player props parlay for a specific sport.
        Uses source signals to determine direction and confidence.
        """
        picks = []
        props_used = set()

        # Get games for this sport only
        all_games = [(g, sport) for g in self.games.get(sport, [])]

        # Simulate player props based on available games
        simulated_props = self._simulate_player_props(all_games)

        for prop in simulated_props:
            # Skip rest day players (they are OUT)
            if prop.get("rest_day", False):
                continue
            if len(picks) >= num_legs:
                break

            # Create unique key to avoid duplicates
            prop_key = f"{prop['player']}_{prop['stat_type']}"
            if prop_key in props_used:
                continue
            props_used.add(prop_key)

            # Get source signal
            signal = self.sources.get_signal(
                prop["sport"], "prop",
                [prop["team"]]
            )

            pick = PropPick(
                player=prop["player"],
                team=prop["team"],
                stat_type=prop["stat_type"],
                line=prop["line"],
                direction=signal["direction"],
                odds=config.DEFAULT_PROP_ODDS,
                source_signal=self._get_strongest_source(signal),
                confidence=signal["confidence"]
            )
            picks.append(pick)

        return picks

    def generate_winners_parlay(self, sport: str, num_legs: int = 3) -> List[WinnerPick]:
        """
        Generate a game winners parlay for a specific sport (spread/total/ML mix).
        Uses source signals to pick winners.
        """
        picks = []
        teams_used = set()

        all_games = [(g, sport) for g in self.games.get(sport, []) if g.status == "scheduled"]

        # For the mix: 1 spread + 1 total + 1 ML when possible
        pick_types_needed = ["spread", "total", "moneyline"]
        pick_types_used = []

        for game, sport in all_games:
            if len(picks) >= num_legs:
                break

            # Pick based on source signals
            signal = self.sources.get_signal(
                sport, "winner",
                [game.home_team.abbreviation, game.away_team.abbreviation]
            )

            # Determine which team to pick
            home_favored = signal["signal_strength"] > 0.3 if random.random() > 0.3 else random.random() > 0.5

            if home_favored:
                pick_team = game.home_team
                opp_team = game.away_team
            else:
                pick_team = game.away_team
                opp_team = game.home_team

            # Avoid duplicate teams
            if pick_team.abbreviation in teams_used:
                pick_team, opp_team = opp_team, pick_team
            if pick_team.abbreviation in teams_used:
                continue

            teams_used.add(pick_team.abbreviation)

            # Determine pick type - mix spread, total, and moneyline
            spread_available = sport in ["NBA", "NHL", "MLB"]
            total_available = sport in ["NBA", "NHL", "MLB"]

            # Cycle through pick types
            pick_type = pick_types_needed[len(pick_types_used) % len(pick_types_needed)]

            # Generate line and odds
            if pick_type == "spread":
                line = self._generate_spread(sport)
                odds = config.DEFAULT_PROP_ODDS
            elif pick_type == "total":
                line = self._generate_total(sport)
                odds = config.DEFAULT_PROP_ODDS
            else:  # moneyline
                line = 0
                favorite = home_favored
                odds = self.odds.get_default_odds(favorite, sport.lower())

            pick_types_used.append(pick_type)

            pick = WinnerPick(
                team=pick_team.abbreviation,
                opponent=opp_team.abbreviation,
                pick_type=pick_type,
                line=line,
                odds=odds,
                source_signal=self._get_strongest_source(signal),
                confidence=signal["confidence"]
            )
            picks.append(pick)

        return picks

    def generate_league_parlays(self, sport: str) -> Dict[str, List]:
        """
        Generate per-league parlays for a specific sport.
        Returns dict with 'props' and 'game_picks' lists.
        """
        props = self.generate_props_parlay(sport, config.PARLAY_LEGS)
        game_picks = self.generate_winners_parlay(sport, config.PARLAY_LEGS)
        return {
            "props": props,
            "game_picks": game_picks
        }

    def generate_confidence_parlay(self, min_confidence: int = 70) -> List[Dict]:
        """
        Generate a cross-league confidence parlay with 3-5 legs.
        Only includes picks with >= min_confidence% confidence.
        Uses higher confidence threshold (default 70%).
        """
        all_picks = []

        for sport in config.SPORTS:
            # Get props
            props = self.generate_props_parlay(sport, config.PARLAY_LEGS)
            for prop in props:
                # DEFENSIVE CHECK: Verify player is actually active on DK slate
                # This is a safety net in case rest_day flag wasn't set correctly upstream
                if not self.dk.is_player_active_dk(prop.player, prop.team, sport):
                    logger.warning(f"Skipping {prop.player} ({prop.team}) in confidence parlay - not in DK slate")
                    continue
                if prop.confidence >= min_confidence:
                    all_picks.append({
                        "type": "prop",
                        "sport": sport,
                        "pick": prop,
                        "confidence": prop.confidence
                    })

            # Get game picks
            game_picks = self.generate_winners_parlay(sport, config.PARLAY_LEGS)
            for pick in game_picks:
                if pick.confidence >= min_confidence:
                    all_picks.append({
                        "type": "game",
                        "sport": sport,
                        "pick": pick,
                        "confidence": pick.confidence
                    })

        # Sort by confidence and take top 5
        all_picks.sort(key=lambda x: x["confidence"], reverse=True)
        return all_picks[:5]

    def _simulate_player_props(self, games: List[tuple]) -> List[Dict]:
        """
        Simulate player props based on available games.
        Maps real teams to star players with realistic lines.
        """
        simulated = []

        # Star players mapped by team name (handles full names + abbreviations)
        team_players = {
            "PHI": [("Tyrese Maxey", "points", 23.5), ("Paul George", "threes", 3.5)],
            "WSH": [("Jordan Poole", "points", 19.5)],
            "ORL": [("Paolo Banchero", "points", 22.5), ("Franz Wagner", "rebounds", 5.5)],
            "ATL": [("Trae Young", "points", 25.5), ("Jalen Johnson", "rebounds", 7.5)],
            "MIA": [("Tyler Herro", "points", 21.5), ("Bam Adebayo", "rebounds", 9.5)],
            "BOS": [("Jayson Tatum", "points", 27.5), ("Jaylen Brown", "threes", 3.5)],
            "MEM": [("Jaren Jackson Jr.", "points", 19.5), ("Desmond Bane", "threes", 2.5)],
            "NY": [("Karl-Anthony Towns", "rebounds", 10.5), ("Jalen Brunson", "assists", 6.5)],
            "LAL": [("LeBron James", "points", 25.5), ("Luka Doncic", "rebounds", 7.5)],
            "DEN": [("Nikola Jokic", "assists", 9.5), ("Jamal Murray", "points", 21.5)],
            "GSW": [("Stephen Curry", "points", 28.5), ("Klay Thompson", "threes", 4.5)],
            "MIL": [("Giannis Antetokounmpo", "points", 29.5), ("Damian Lillard", "assists", 7.5)],
            "DAL": [("Kyrie Irving", "points", 24.5), ("Dereck Lively", "rebounds", 6.5)],
            "OKC": [("Shai Gilgeous-Alexander", "points", 31.5), ("Jalen Williams", "threes", 2.5)],
            "CLE": [("Donovan Mitchell", "points", 24.5), ("Darius Garland", "assists", 7.5)],
            "MIN": [("Anthony Edwards", "points", 26.5), ("Julius Randle", "rebounds", 8.5)],
            "HOU": [("Alperen Sengun", "rebounds", 8.5), ("Fred VanVleet", "assists", 6.5)],
            "SAS": [("Victor Wembanyama", "blocks", 3.5), ("Chris Paul", "assists", 8.5)],
            "PHX": [("Kevin Durant", "points", 26.5), ("Devin Booker", "threes", 3.5)],
            "NOP": [("Zion Williamson", "points", 22.5), ("CJ McCollum", "threes", 3.5)],
            "SAC": [("De'Aaron Fox", "points", 24.5), ("Domantas Sabonis", "rebounds", 11.5)],
            "IND": [("Tyrese Haliburton", "assists", 10.5), ("Pascal Siakam", "points", 20.5)],
            "UTAH": [("Lauri Markkanen", "points", 20.5)],
            "CHA": [("LaMelo Ball", "points", 23.5), ("Miles Bridges", "rebounds", 5.5)],
            "BKN": [("Cameron Thomas", "points", 21.5)],
            "DET": [("Cade Cunningham", "points", 22.5), ("Jaden Ivey", "threes", 2.5)],
            "TOR": [("Scottie Barnes", "rebounds", 7.5), ("RJ Barrett", "points", 20.5)],
            "POR": [("Anfernee Simons", "points", 22.5)],
            "CHI": [("Zach LaVine", "points", 24.5), ("Nikola Vucevic", "rebounds", 9.5)],
            " LAC": [("Kawhi Leonard", "points", 23.5), ("James Harden", "assists", 8.5)],
            "DET": [("Cade Cunningham", "points", 22.5)],
            # NHL teams
            "NHL": [
                ("Connor McDavid", "points", 1.5),
                ("Leon Draisaitl", "points", 1.5),
                ("Nathan MacKinnon", "points", 1.5),
                ("Auston Matthews", "goals", 0.5),
            ],
            # MLB teams
            "NYY": [("Aaron Judge", "hits", 0.5), ("Juan Soto", "runs", 0.5)],
            "LAD": [("Mookie Betts", "hits", 0.5), ("Shohei Ohtani", "strikeouts", 6.5)],
            "BOS": [("Rafael Devers", "RBI", 0.5)],
            "PHI": [("Kyle Schwarber", "home_runs", 0.5)],
            "HOU": [("Jose Altuve", "hits", 0.5)],
            "ATL": [("Ronald Acuna Jr.", "runs", 0.5)],
            "SD": [("Manny Machado", "RBI", 0.5)],
            "STL": [("Nolan Arenado", "RBI", 0.5)],
            "CHC": [("Christopher Morel", "home_runs", 0.5)],
            "NYM": [("Francisco Lindor", "hits", 0.5)],
            "TOR": [("Vladimir Guerrero Jr.", "RBI", 0.5)],
            "SEA": [("Julio Rodriguez", "runs", 0.5)],
            "TEX": [("Corey Seager", "hits", 0.5)],
            "MIL": [("Christian Yelich", "home_runs", 0.5)],
            "CLE": [("Jose Ramirez", "RBI", 0.5)],
            "SF": [("Logan Webb", "strikeouts", 6.5)],
            "CIN": [("Elly De La Cruz", "runs", 0.5)],
            "MIA": [("Jazz Chisholm", "home_runs", 0.5)],
            "MIN": [("Carlos Correa", "hits", 0.5)],
            "LAA": [("Mike Trout", "home_runs", 0.5)],
            "COL": [("Ryan McMahon", "RBI", 0.5)],
            "OAK": [("Lawrence Butler", "runs", 0.5)],
            "KC": [("Bobby Witt Jr.", "hits", 0.5)],
            "TB": [("Isaac Paredes", "RBI", 0.5)],
            "PIT": [("Oneil Cruz", "home_runs", 0.5)],
            "BAL": [("Gunnar Henderson", "runs", 0.5)],
            "AZ": [("Ketel Marte", "hits", 0.5)],
            "WSH": [("James Wood", "runs", 0.5)],
        }

        # NHL team abbreviation to star players
        nhl_team_players = {
            "EDM": [("Connor McDavid", "points", 1.5), ("Leon Draisaitl", "points", 1.5)],
            "COL": [("Nathan MacKinnon", "points", 1.5)],
            "TOR": [("Auston Matthews", "goals", 0.5), ("Mitch Marner", "points", 1.5)],
            "BOS": [("David Pastrnak", "goals", 0.5)],
            "NYR": [("Artemi Panarin", "points", 1.5)],
            "NYI": [("Bo Horvat", "goals", 0.5)],
            "FLA": [("Matthew Tkachuk", "points", 1.5)],
            "TBL": [("Nikita Kucherov", "points", 1.5)],
            "CAR": [("Sebastian Aho", "points", 1.5)],
            "NJD": [("Jack Hughes", "points", 1.5)],
            "PIT": [("Sidney Crosby", "points", 1.5)],
            "WSH": [("Alex Ovechkin", "goals", 0.5)],
            "PHI": [("Travis Konecny", "goals", 0.5)],
            "BUF": [("Tage Thompson", "goals", 0.5)],
            "OTT": [("Brady Tkachuk", "points", 0.5)],
            "MTL": [("Cole Caufield", "goals", 0.5)],
            "DET": [("Lucas Raymond", "points", 0.5)],
            "CBJ": [("Johnny Gaudreau", "points", 0.5)],
            "STL": [("Robert Thomas", "points", 0.5)],
            "MIN": [("Kirill Kaprizov", "points", 1.5)],
            "NSH": [("Roman Josi", "points", 0.5)],
            "DAL": [("Jason Robertson", "points", 0.5)],
            "WPG": [("Mark Scheifele", "points", 0.5)],
            "CGY": [("Nazem Kadri", "points", 0.5)],
            "ANA": [("Leo Carlsson", "goals", 0.5)],
            "LA": [("Anze Kopitar", "points", 0.5)],
            "SJ": [("Timo Meier", "goals", 0.5)],
            "VGK": [("Jack Eichel", "points", 1.5)],
            "ARI": [("Clayton Keller", "points", 0.5)],
            "CHI": [("Patrick Kane", "points", 0.5)],
        }

        for game, sport in games:
            home_abbr = game.home_team.abbreviation
            away_abbr = game.away_team.abbreviation

            # Select the right player map based on sport
            if sport == "NHL":
                player_map = nhl_team_players
            else:
                player_map = team_players

            # Check if we have players for these teams
            for abbr in [home_abbr, away_abbr]:
                if abbr in player_map:
                    players = player_map[abbr]
                    for player, stat, line in players[:2]:
                        # Check if player is active on DK slate
                        is_active = self.dk.is_player_active_dk(player, abbr, sport)
                        
                        if is_active:
                            simulated.append({
                                "player": player,
                                "team": abbr,
                                "stat_type": stat,
                                "line": line,
                                "sport": sport,
                                "dk_active": True,
                                "rest_day": False,  # Explicitly set - NOT a rest day
                            })
                        else:
                            # Log warning for rest day / missing player
                            warning_msg = f"⚠️ {player} ({abbr}) - likely REST DAY or INJURED (not in DK slate)"
                            logger.warning(warning_msg)
                            
                            # Track rest day warnings by sport
                            if sport not in self._rest_day_warnings:
                                self._rest_day_warnings[sport] = []
                            self._rest_day_warnings[sport].append(f"{player} ({abbr})")
                            
                            # Still include with rest_day flag for visibility
                            simulated.append({
                                "player": player,
                                "team": abbr,
                                "stat_type": stat,
                                "line": line,
                                "sport": sport,
                                "dk_active": False,
                                "rest_day": True,
                            })

        return simulated

    def _generate_spread(self, sport: str) -> float:
        """Generate a realistic spread line."""
        spreads = {
            "NBA": [-6.5, -5.5, -4.5, -3.5, -2.5, -1.5],
            "NHL": [-1.5, 1.5],
            "MLB": [-1.5, 1.5],
        }
        return random.choice(spreads.get(sport, [-3.5]))

    def _generate_total(self, sport: str) -> float:
        """Generate a realistic total line."""
        totals = {
            "NBA": [210.5, 220.5, 225.5, 230.5, 235.5, 240.5],
            "NHL": [5.5, 6.0, 6.5, 7.0],
            "MLB": [7.5, 8.0, 8.5, 9.0, 9.5, 10.0],
        }
        return random.choice(totals.get(sport, [7.5]))

    def _get_strongest_source(self, signal: Dict) -> str:
        """Get the source with strongest signal."""
        # Simulate - in production would check actual sources
        sources = list(config.SOURCES.items())
        strongest = max(sources, key=lambda x: x[1]["weight"])
        return strongest[1]["name"]

    def calculate_parlay_payout(self, picks: List) -> Dict[str, Any]:
        """Calculate parlay odds and payout."""
        formatted_picks = []
        for pick in picks:
            if isinstance(pick, PropPick):
                formatted_picks.append({"odds": pick.odds})
            else:
                formatted_picks.append({"odds": pick.odds})

        return self.odds.calculate_parlay_odds(formatted_picks)

    def format_report(self) -> str:
        """Format the betting report for Discord."""
        # Count total games
        total_games = sum(len(games) for games in self.games.values())

        # Get date
        date_str = datetime.now().strftime("%m/%d/%Y")

        # Sports emoji map
        sport_emoji = {
            "NBA": "🏀",
            "NHL": "🧊",
            "MLB": "⚾"
        }

        # Build report
        report = []
        report.append("🍝 **UNCLE VITO'S BETTING REPORT** 🍝")
        report.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        report.append(f"📅 {date_str} | **{total_games}** games | 3-Leg Parlays")
        report.append("")

        # Generate parlays for each sport
        league_parlays = {}
        for sport in config.SPORTS:
            if sport in self.games and self.games[sport]:
                league_parlays[sport] = self.generate_league_parlays(sport)

        # Format each league section
        for sport in config.SPORTS:
            emoji = sport_emoji.get(sport, "🏆")
            parlays = league_parlays.get(sport, {"props": [], "game_picks": []})
            props = parlays.get("props", [])
            game_picks = parlays.get("game_picks", [])

            report.append(f"{emoji} **{sport}**")
            report.append("")

            # Props section
            report.append(f"  Props ({config.PARLAY_LEGS}-Leg):")
            if not props:
                report.append("  _No props available_")
            else:
                for i, pick in enumerate(props, 1):
                    emoji_dir = "📈" if pick.direction == "over" else "📉"
                    report.append(
                        f"  {i}. {pick.player} ({pick.team}) - **{pick.direction.upper()}** "
                        f"{pick.stat_type} {pick.line}"
                    )
                props_payout = self.calculate_parlay_payout(props)
                avg_conf = sum(p.confidence for p in props) // max(len(props), 1)
                report.append(f"  📈 Odds: **+{props_payout['payout']}** | 🎯 {avg_conf}%")

            report.append("")

            # Game picks section (spread/total/ML mix)
            report.append(f"  Spread/Total/ML ({config.PARLAY_LEGS}-Leg):")
            if not game_picks:
                report.append("  _No games available_")
            else:
                for i, pick in enumerate(game_picks, 1):
                    if pick.pick_type == "spread":
                        line_str = f"({pick.line})"
                    elif pick.pick_type == "total":
                        line_str = f"O/U {pick.line}"
                    else:
                        line_str = "ML"
                    report.append(
                        f"  {i}. {pick.team} vs {pick.opponent} - **{pick.team}** {line_str}"
                    )
                winners_payout = self.calculate_parlay_payout(game_picks)
                avg_conf = sum(p.confidence for p in game_picks) // max(len(game_picks), 1)
                report.append(f"  📈 Odds: **+{winners_payout['payout']}** | 🎯 {avg_conf}%")

            report.append("")

        # Confidence Parlay (cross-league)
        report.append("🌐 **CONFIDENCE PARLAY** (all leagues)")
        report.append("")

        confidence_picks = self.generate_confidence_parlay(min_confidence=65)

        if not confidence_picks:
            report.append("_No high-confidence picks available today_")
        else:
            for i, pick_data in enumerate(confidence_picks, 1):
                sport = pick_data["sport"]
                emoji = sport_emoji.get(sport, "🏆")
                pick = pick_data["pick"]

                if pick_data["type"] == "prop":
                    emoji_dir = "📈" if pick.direction == "over" else "📉"
                    report.append(
                        f"{i}. {emoji} {pick.player} - **{pick.direction.upper()}** "
                        f"{pick.stat_type} {pick.line} ({pick.confidence}%)"
                    )
                else:
                    if pick.pick_type == "spread":
                        line_str = f"({pick.line})"
                    elif pick.pick_type == "total":
                        line_str = f"O/U {pick.line}"
                    else:
                        line_str = "ML"
                    report.append(
                        f"{i}. {emoji} {pick.team} - **{pick.team}** {line_str} ({pick.confidence}%)"
                    )

            # Calculate combined odds
            conf_picks_formatted = [{"odds": p["pick"].odds} for p in confidence_picks]
            conf_payout = self.odds.calculate_parlay_odds(conf_picks_formatted)
            avg_conf = sum(p["confidence"] for p in confidence_picks) // len(confidence_picks)
            report.append("")
            report.append(
                f"🌐 Odds: **+{conf_payout['payout']}** | 🎯 **{avg_conf}%** confidence | "
                f"{len(confidence_picks)} legs"
            )

        report.append("")
        report.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        
        # Show rest day warnings if any players are missing from DK slate
        if self._rest_day_warnings:
            report.append("")
            report.append("🛋️ **POSSIBLE REST DAYS** (not in DK DFS slate):")
            for sport, players in self._rest_day_warnings.items():
                emoji = sport_emoji.get(sport, "🏆")
                for player_info in players:
                    report.append(f"  {emoji} {player_info}")
        
        report.append("")
        report.append("⚠️ _Do your own homework. Uncle Vito don't miss._")

        return "\n".join(report)

    def generate_report(self) -> str:
        """Generate the full betting report."""
        # Clear rest day warnings from previous report
        self._rest_day_warnings = {}
        
        # Fetch games
        self.fetch_todays_games()

        # Report is generated on-the-fly in format_report now
        return self.format_report()


def main():
    """Main entry point."""
    print("🍝 Generating Uncle Vito's Betting Report...")
    report = UncleVitoReport()
    output = report.generate_report()
    print(output)
    return output


if __name__ == "__main__":
    main()
