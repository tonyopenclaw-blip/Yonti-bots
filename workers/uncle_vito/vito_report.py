#!/usr/bin/env python3
"""
Uncle Vito's Betting Report Generator 🍝
Fetches sports data from ESPN API and generates daily betting reports.
"""

import json
import math
import random
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
import config

try:
    import requests
except ImportError:
    requests = None


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
            "NCAAB": ("basketball", "mens-college-basketball"),
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
        self.games: Dict[str, List[Game]] = {}
        self.prop_picks: List[PropPick] = []
        self.winner_picks: List[WinnerPick] = []

    def fetch_todays_games(self) -> Dict[str, List[Game]]:
        """Fetch today's games across all configured sports."""
        today = datetime.now().strftime("%Y%m%d")

        for sport in config.SPORTS:
            data = self.espn.fetch_scoreboard(sport, today)
            self.games[sport] = self.espn.parse_games(data, sport)

        return self.games

    def generate_props_parlay(self, num_legs: int = 4) -> List[PropPick]:
        """
        Generate a 4-leg player props parlay.
        Uses source signals to determine direction and confidence.
        """
        picks = []
        props_used = set()

        # Flatten all games for props
        all_games = []
        for sport, games in self.games.items():
            all_games.extend([(g, sport) for g in games])

        # Simulate player props based on available games
        # In production, would fetch from actual props API
        simulated_props = self._simulate_player_props(all_games)

        for prop in simulated_props:
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

        self.prop_picks = picks
        return picks

    def generate_winners_parlay(self, num_legs: int = 4) -> List[WinnerPick]:
        """
        Generate a 4-leg game winners parlay.
        Uses source signals to pick winners.
        """
        picks = []
        teams_used = set()

        all_games = []
        for sport, games in self.games.items():
            all_games.extend([(g, sport) for g in games if g.status == "scheduled"])

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

            # Determine if spread or moneyline
            spread_available = sport in ["NBA", "NCAAB"]  # Basketball has spreads
            pick_type = "spread" if spread_available and random.random() > 0.5 else "moneyline"

            # Generate line and odds
            if pick_type == "spread":
                line = self._generate_spread(sport)
                odds = config.DEFAULT_PROP_ODDS
            else:
                line = 0
                favorite = home_favored  # Simplified
                odds = self.odds.get_default_odds(favorite, sport.lower())

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

        self.winner_picks = picks
        return picks

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
        }

        for game, sport in games:
            home_abbr = game.home_team.abbreviation
            away_abbr = game.away_team.abbreviation

            # Check if we have players for these teams
            for abbr in [home_abbr, away_abbr]:
                if abbr in team_players:
                    players = team_players[abbr]
                    for player, stat, line in players[:2]:
                        simulated.append({
                            "player": player,
                            "team": abbr,
                            "stat_type": stat,
                            "line": line,
                            "sport": sport
                        })

        return simulated

    def _generate_spread(self, sport: str) -> float:
        """Generate a realistic spread line."""
        spreads = {
            "NBA": [-6.5, -5.5, -4.5, -3.5, -2.5, -1.5],
            "NCAAB": [-5.5, -4.5, -3.5, -2.5],
            "NHL": [-1.5, 1.5],
        }
        return random.choice(spreads.get(sport, [-3.5]))

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

        # Sports list
        sports_active = [sport for sport, games in self.games.items() if games]
        sports_str = ", ".join(sports_active) if sports_active else "NBA, NHL, NCAAB"

        # Build report
        report = []
        report.append("🍝 **UNCLE VITO'S BETTING REPORT** 🍝")
        report.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        report.append(f"📅 Generated: {date_str} | {sports_str} — **{total_games}** games today")
        report.append("")

        # Props Parlay
        report.append("🏆 **TOP PROPS (4-Leg Parlay)**")
        report.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        if not self.prop_picks:
            report.append("_No props available today_")
        else:
            for i, pick in enumerate(self.prop_picks, 1):
                emoji = "📈" if pick.direction == "over" else "📉"
                report.append(
                    f"{i}. {pick.player} ({pick.team}) - **{pick.direction.upper()}** "
                    f"{pick.stat_type} {pick.line} @ {pick.odds}"
                )

            props_payout = self.calculate_parlay_payout(self.prop_picks)
            avg_confidence = sum(p.confidence for p in self.prop_picks) // len(self.prop_picks)
            report.append("")
            report.append(
                f"📈 Odds: **+{props_payout['payout']}** | "
                f"🎯 **{avg_confidence}%** confidence"
            )

        report.append("")
        report.append("🏆 **GAME WINNERS (4-Leg Parlay)**")
        report.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        if not self.winner_picks:
            report.append("_No games available_")
        else:
            for i, pick in enumerate(self.winner_picks, 1):
                if pick.pick_type == "spread":
                    line_str = f"({pick.line})"
                else:
                    line_str = ""

                report.append(
                    f"{i}. {pick.team} vs {pick.opponent} - **{pick.team}** {line_str} @ {pick.odds}"
                )

            winners_payout = self.calculate_parlay_payout(self.winner_picks)
            avg_confidence = sum(p.confidence for p in self.winner_picks) // len(self.winner_picks)
            report.append("")
            report.append(
                f"📈 Odds: **+{winners_payout['payout']}** | "
                f"🎯 **{avg_confidence}%** confidence"
            )

        report.append("")
        report.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        report.append("⚠️ _Do your own homework. Uncle Vito don't miss._")

        return "\n".join(report)

    def generate_report(self) -> str:
        """Generate the full betting report."""
        # Fetch games
        self.fetch_todays_games()

        # Generate parlays
        self.generate_props_parlay()
        self.generate_winners_parlay()

        # Format and return
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
