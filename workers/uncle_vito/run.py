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


def run(sport_filter: list = None, discord_output: bool = False, channel: str = None, use_sharp: bool = True):
    """Run the report generator.
    
    Args:
        sport_filter: List of sports to include (NBA, NHL, MLB)
        discord_output: Whether to send to Discord
        channel: Discord channel name
        use_sharp: Whether to apply X sharp consensus boost (default True)
    """
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

    # Pre-fetch sharp consensus if enabled (for display in report)
    if use_sharp:
        print("🍝 Fetching sharp consensus from X...")
        report.fetch_sharp_consensus()

    # Format report
    output = report.format_report()

    # Print to console
    print("\n" + output)

    # Send to Discord if requested
    if discord_output:
        try:
            import subprocess
            import json
            # Use proper JSON encoding to preserve Unicode emoji
            payload = json.dumps({"content": output})
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

    # Generate and write HTML report
    try:
        html_output = report.format_report_html()
        html_paths = [
            "/home/ubuntu/.openclaw/workspace/vito.html",
            "/var/www/html/vito.html",
        ]
        for path in html_paths:
            try:
                with open(path, "w") as f:
                    f.write(html_output)
                print(f"🍝 HTML written to {path}")
            except Exception as e:
                print(f"⚠️ Failed to write HTML to {path}: {e}")
    except Exception as e:
        print(f"⚠️ Failed to generate HTML: {e}")

    return output


def main():
    parser = argparse.ArgumentParser(description="Uncle Vito's Betting Report")
    parser.add_argument("--sport", "-s", action="append", help="Filter by sport (NBA, NHL, MLB). Can specify multiple.")
    parser.add_argument("--discord", "-d", action="store_true", help="Send to Discord")
    parser.add_argument("--channel", "-c", default="uncle-vito", help="Discord channel")
    parser.add_argument("--no-sharp", action="store_true", help="Disable X sharp consensus boost")
    args = parser.parse_args()

    # Default to all sports if none specified
    sport_filter = args.sport if args.sport else None

    run(sport_filter=sport_filter, discord_output=args.discord, channel=args.channel, use_sharp=not args.no_sharp)


if __name__ == "__main__":
    main()
