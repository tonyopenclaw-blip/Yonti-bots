#!/usr/bin/env python3
"""
Uncle Vito CLI - Run the betting report generator.
Usage: python run.py [--discord] [--channel CHANNEL]
"""

import sys
import argparse
import os

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vito_report import UncleVitoReport


def run(sport_filter: str = None, discord_output: bool = False, channel: str = None):
    """Run the report generator."""
    report = UncleVitoReport()

    # Fetch games
    print("📡 Fetching game data from ESPN...")
    report.fetch_todays_games()

    # Filter sports if specified
    if sport_filter:
        sport_upper = sport_filter.upper()
        if sport_upper in report.games:
            filtered = {sport_upper: report.games[sport_upper]}
            report.games = filtered

    # Generate parlays
    print("🎯 Building props parlay...")
    report.generate_props_parlay()

    print("🏆 Building winners parlay...")
    report.generate_winners_parlay()

    # Format report
    output = report.format_report()

    # Print to console
    print("\n" + output)

    # Send to Discord if requested
    if discord_output:
        try:
            from message import message
            target = channel or "uncle-vito"
            message(action="send", channel="discord", target=target, message=output)
            print(f"\n✅ Report sent to Discord channel: {target}")
        except Exception as e:
            print(f"\n⚠️ Could not send to Discord: {e}")

    return output


def main():
    parser = argparse.ArgumentParser(description="Uncle Vito's Betting Report")
    parser.add_argument("--sport", "-s", help="Filter by sport (NBA, NHL, NCAAB)")
    parser.add_argument("--discord", "-d", action="store_true", help="Send to Discord")
    parser.add_argument("--channel", "-c", default="uncle-vito", help="Discord channel")
    args = parser.parse_args()

    run(sport_filter=args.sport, discord_output=args.discord, channel=args.channel)


if __name__ == "__main__":
    main()
