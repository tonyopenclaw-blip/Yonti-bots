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
import config


def run(sport_filter: list = None, discord_output: bool = False, channel: str = None):
    """Run the report generator."""
    report = UncleVitoReport()

    # Fetch games
    print("📡 Fetching game data from ESPN...")
    report.fetch_todays_games()

    # Filter sports if specified
    if sport_filter:
        sport_upper_list = [s.upper() for s in sport_filter]
        filtered = {}
        for sport_upper in sport_upper_list:
            if sport_upper in report.games:
                filtered[sport_upper] = report.games[sport_upper]
        # Also filter config.SPORTS temporarily
        original_sports = config.SPORTS.copy()
        config.SPORTS = [s for s in config.SPORTS if s in filtered]
        report.games = filtered

    # Format report
    output = report.format_report()

    # Print to console
    print("\n" + output)

    # Send to Discord if requested
    if discord_output:
        try:
            import subprocess
            import json as json_module
            # Escape the message for JSON
            escaped_output = output.replace('"', '\\"').replace('\n', '\\n')
            payload = f'{{"content": "{escaped_output}"}}'
            result = subprocess.run(
                ["curl", "-s", "-X", "POST", "-H", "Content-Type: application/json",
                 "-d", payload, config.DISCORD_WEBHOOK_URL],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                print(f"\n✅ Report sent to Discord channel: {channel or 'uncle-vito'}")
            else:
                print(f"\n⚠️ Could not send to Discord: curl returned {result.returncode}")
        except Exception as e:
            print(f"\n⚠️ Could not send to Discord: {e}")

    return output


def main():
    parser = argparse.ArgumentParser(description="Uncle Vito's Betting Report")
    parser.add_argument("--sport", "-s", action="append", help="Filter by sport (NBA, NHL, MLB). Can specify multiple.")
    parser.add_argument("--discord", "-d", action="store_true", help="Send to Discord")
    parser.add_argument("--channel", "-c", default="uncle-vito", help="Discord channel")
    args = parser.parse_args()

    # Default to all sports if none specified
    sport_filter = args.sport if args.sport else None

    run(sport_filter=sport_filter, discord_output=args.discord, channel=args.channel)


if __name__ == "__main__":
    main()
