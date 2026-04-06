#!/usr/bin/env python3
"""
Sharp Scanner Module for Uncle Vito 🍝
Scrapes X (Twitter) sharp bettor accounts to weight Vito's picks.

Uses Apify API to fetch tweets from 4 sharp bettor accounts:
- dangambleai
- codybrownbets  
- harrylockpicks
- cookitup31

Calculates "sharp consensus" - how many sharps mention each player.
"""

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Dict, List, Set, Optional, Any
from dataclasses import dataclass, field

try:
    import requests
except ImportError:
    requests = None

logger = logging.getLogger("uncle_vito.sharp_scanner")

# ============================================================
# CONFIGURATION
# ============================================================

APIFY_API_KEY = "apify_api_sK4vzx6r1hzexr7TA2muKebeQWqChT2psmmB"
APIFY_ACTOR = "apify/twitter-scraper"

# Sharp bettor accounts to track
SHARP_ACCOUNTS = [
    "dangambleai",
    "codybrownbets",
    "harrylockpicks",
    "cookitup31",
]

# Account weights (can be tuned based on historical accuracy)
ACCOUNT_WEIGHTS = {
    "dangambleai": 0.30,
    "codybrownbets": 0.25,
    "harrylockpicks": 0.20,
    "cookitup31": 0.25,
}

# Confidence boost per sharp consensus (added per account mentioning)
SHARP_CONSENSUS_BOOST = 5  # +5% confidence per sharp mentioning player

# ============================================================
# DATA STRUCTURES
# ============================================================

@dataclass
class SharpMention:
    """Represents a player's mention by a sharp bettor."""
    player_name: str
    account: str
    tweet_text: str
    tweet_url: str
    timestamp: datetime
    bet_direction: str = ""  # "over", "under", "play", "fade"

@dataclass
class PlayerSharpScore:
    """Aggregated sharp data for a player."""
    player_name: str
    mentions: List[SharpMention] = field(default_factory=list)
    consensus_score: float = 0.0  # Weighted score based on account weights
    raw_count: int = 0  # Number of accounts mentioning
    sharp_direction: str = ""  # "over" or "under" if consensus
    is_sharp_fade: bool = False  # True if sharps fade this player
    confidence_boost: int = 0  # Additional confidence from sharp consensus

# ============================================================
# APIFY TWITTER SCRAPER
# ============================================================

class ApifyTwitterClient:
    """Client for scraping Twitter via Apify API."""
    
    BASE_URL = "https://api.apify.com/v2/acts"
    
    def __init__(self, api_key: str = APIFY_API_KEY):
        self.api_key = api_key
        self.session = requests.Session() if requests else None
    
    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
    
    def get_tweets_by_username(self, username: str, max_tweets: int = 50) -> List[Dict]:
        """
        Fetch recent tweets from a specific user using Apify twitter-scraper actor.
        
        Args:
            username: Twitter handle (without @)
            max_tweets: Maximum number of tweets to fetch
            
        Returns:
            List of tweet objects
        """
        if not requests:
            logger.warning("requests library not available")
            return []
        
        # Using Apify's twitter-scraper actor with specific user
        url = f"{self.BASE_URL}/{APIFY_ACTOR}/runs"
        
        # Start the actor with user tweets input
        start_data = {
            "usernames": [username],
            "maxTweets": max_tweets,
            "tweetLanguage": "en",
        }
        
        try:
            # Start the run
            response = self.session.post(
                url,
                headers=self._headers(),
                json=start_data,
                timeout=30
            )
            
            if response.status_code != 200 and response.status_code != 201:
                logger.warning(f"Apify start run failed for @{username}: {response.status_code}")
                return []
            
            run_data = response.json()
            run_id = run_data.get("data", {}).get("id")
            
            if not run_id:
                logger.warning(f"No run ID returned for @{username}")
                return []
            
            # Poll for completion
            import time
            max_wait = 60  # seconds
            waited = 0
            
            while waited < max_wait:
                time.sleep(2)
                waited += 2
                
                status_url = f"{self.BASE_URL}/{APIFY_ACTOR}/runs/{run_id}"
                status_resp = self.session.get(status_url, headers=self._headers(), timeout=30)
                
                if status_resp.status_code == 200:
                    status_data = status_resp.json()
                    status = status_data.get("data", {}).get("status", "")
                    
                    if status == "SUCCEEDED":
                        break
                    elif status in ["FAILED", "ABORTED", "TIMED_OUT"]:
                        logger.warning(f"Apify run {status} for @{username}")
                        return []
            
            # Get dataset items
            dataset_id = run_data.get("data", {}).get("defaultDatasetId")
            if not dataset_id:
                # Try to get from status response
                status_url = f"{self.BASE_URL}/{APIFY_ACTOR}/runs/{run_id}"
                status_resp = self.session.get(status_url, headers=self._headers(), timeout=30)
                if status_resp.status_code == 200:
                    dataset_id = status_resp.json().get("data", {}).get("defaultDatasetId")
            
            if not dataset_id:
                logger.warning(f"No dataset ID for @{username}")
                return []
            
            items_url = f"https://api.apify.com/v2/datasets/{dataset_id}/items"
            items_resp = self.session.get(items_url, headers=self._headers(), timeout=30)
            
            if items_resp.status_code == 200:
                tweets = items_resp.json()
                logger.info(f"Fetched {len(tweets)} tweets from @{username}")
                return tweets
            else:
                logger.warning(f"Failed to get tweets from @{username}: {items_resp.status_code}")
                return []
                
        except Exception as e:
            logger.error(f"Error fetching tweets from @{username}: {e}")
            return []
    
    def search_tweets(self, query: str, max_tweets: int = 100) -> List[Dict]:
        """
        Search tweets by keyword/hashtag.
        
        Args:
            query: Search query (e.g., "MLB props", "player props tonight")
            max_tweets: Maximum tweets to fetch
            
        Returns:
            List of matching tweets
        """
        if not requests:
            logger.warning("requests library not available")
            return []
        
        url = f"{self.BASE_URL}/{APIFY_ACTOR}/runs"
        
        start_data = {
            "searchTerms": [query],
            "maxTweets": max_tweets,
            "tweetLanguage": "en",
        }
        
        try:
            response = self.session.post(
                url,
                headers=self._headers(),
                json=start_data,
                timeout=30
            )
            
            if response.status_code not in (200, 201):
                logger.warning(f"Apify search failed for '{query}': {response.status_code}")
                return []
            
            run_data = response.json()
            run_id = run_data.get("data", {}).get("id")
            
            if not run_id:
                return []
            
            # Poll for completion
            import time
            max_wait = 90
            waited = 0
            
            while waited < max_wait:
                time.sleep(3)
                waited += 3
                
                status_url = f"{self.BASE_URL}/{APIFY_ACTOR}/runs/{run_id}"
                status_resp = self.session.get(status_url, headers=self._headers(), timeout=30)
                
                if status_resp.status_code == 200:
                    status = status_resp.json().get("data", {}).get("status", "")
                    if status == "SUCCEEDED":
                        break
                    elif status in ["FAILED", "ABORTED", "TIMED_OUT"]:
                        return []
            
            dataset_id = run_data.get("data", {}).get("defaultDatasetId")
            if not dataset_id:
                return []
            
            items_url = f"https://api.apify.com/v2/datasets/{dataset_id}/items"
            items_resp = self.session.get(items_url, headers=self._headers(), timeout=30)
            
            if items_resp.status_code == 200:
                tweets = items_resp.json()
                logger.info(f"Search '{query}' returned {len(tweets)} tweets")
                return tweets
            return []
            
        except Exception as e:
            logger.error(f"Error searching tweets for '{query}': {e}")
            return []

# ============================================================
# PLAYER NAME EXTRACTION
# ============================================================

class PlayerNameExtractor:
    """Extracts player names and bet directions from tweet text."""
    
    # Common name patterns and aliases
    PLAYER_ALIASES = {
        # NBA
        "jayson tatum": "Jayson Tatum",
        "tatum": "Jayson Tatum",
        "jaylen brown": "Jaylen Brown",
        "jb": "Jaylen Brown",
        "jayson": "Jayson Tatum",
        "lebron": "LeBron James",
        "bron": "LeBron James",
        " luka": "Luka Doncic",
        "luka": "Luka Doncic",
        "curry": "Stephen Curry",
        "steph": "Stephen Curry",
        "giannis": "Giannis Antetokounmpo",
        "ad": "Anthony Davis",
        "anthony davis": "Anthony Davis",
        "kd": "Kevin Durant",
        "kevin durant": "Kevin Durant",
        "booker": "Devin Booker",
        "devin": "Devin Booker",
        "embiid": "Joel Embiid",
        "joel embiid": "Joel Embiid",
        "shai": "Shai Gilgeous-Alexander",
        "sga": "Shai Gilgeous-Alexander",
        "trae": "Trae Young",
        "trae young": "Trae Young",
        "lamelo": "LaMelo Ball",
        "lamelo ball": "LaMelo Ball",
        "zion": "Zion Williamson",
        "ja morant": "Ja Morant",
        "ja": "Ja Morant",
        "donovan mitchell": "Donovan Mitchell",
        "spida": "Donovan Mitchell",
        # NHL
        "mcdavid": "Connor McDavid",
        "crosby": "Sidney Crosby",
        "ovechkin": "Alex Ovechkin",
        "mackinnon": "Nathan MacKinnon",
        "matthews": "Auston Matthews",
        "drai": "Leon Draisaitl",
        "draisaitl": "Leon Draisaitl",
        # MLB
        "ohtani": "Shohei Ohtani",
        "shohei": "Shohei Ohtani",
        "judge": "Aaron Judge",
        "a judge": "Aaron Judge",
        "soto": "Juan Soto",
        "mookie": "Mookie Betts",
        "mookie betts": "Mookie Betts",
    }
    
    # Bet direction patterns
    DIRECTION_PATTERNS = [
        (r"\b(over|ova|o\')\b.*?(\d+\.?\d*)", "over"),
        (r"(\d+\.?\d*).*?\b(under|una|u\')\b", "under"),
        (r"\bplay\b", "play"),
        (r"\bfade\b", "fade"),
        (r"\btop\b.*?pick", "play"),
        (r"\bmy\s*picks?\b", "play"),
        (r"going\s*(over|under)", lambda m: m.group(1)),
        (r"taking\s*the\s*(over|under)", lambda m: m.group(1)),
        (r"(over|under)\s*\d+\.?\d*", lambda m: m.group(1)),
    ]
    
    # Sports-related keywords to filter noise
    SPORTS_KEYWORDS = [
        "prop", "player", "points", "rebounds", "assists", "threes", "blocks", 
        "steals", "goals", "assists", "shots", "hits", "runs", "rbi", 
        "strikeouts", "home runs", "bonus", "parlay", "bet", "odds", "line",
        "hit rate", "record", "win", "loss", "covers", "sharp", "action"
    ]
    
    def extract_player_bets(self, tweet_text: str) -> List[tuple]:
        """
        Extract player names and bet directions from tweet text.
        
        Returns:
            List of (player_name, direction) tuples
        """
        results = []
        text_lower = tweet_text.lower()
        
        # Check if tweet is sports-related
        if not any(kw in text_lower for kw in self.SPORTS_KEYWORDS):
            return results
        
        # Find mentions using aliases
        found_players = set()
        for alias, full_name in self.PLAYER_ALIASES.items():
            # Use word boundary matching
            pattern = r'\b' + re.escape(alias) + r'\b'
            if re.search(pattern, text_lower):
                found_players.add(full_name)
        
        # Determine direction
        direction = ""
        for pattern, direction_match in self.DIRECTION_PATTERNS:
            if callable(direction_match):
                match = re.search(pattern, text_lower)
                if match:
                    direction = direction_match(match)
                    break
            else:
                if re.search(pattern, text_lower, re.IGNORECASE):
                    direction = direction_match
                    break
        
        # Also check for specific "over" or "under" near player names
        if "over" in text_lower and "under" not in text_lower:
            direction = "over"
        elif "under" in text_lower and "over" not in text_lower:
            direction = "under"
        
        # Add all found players with direction
        for player in found_players:
            results.append((player, direction))
        
        return results

# ============================================================
# SHARP CONSENSUS CALCULATOR
# ============================================================

class SharpConsensusCalculator:
    """Calculates consensus from multiple sharp bettor accounts."""
    
    def __init__(self):
        self.extractor = PlayerNameExtractor()
        self.accounts = SHARP_ACCOUNTS
        self.weights = ACCOUNT_WEIGHTS
    
    def calculate_consensus(self, mentions_by_account: Dict[str, List[SharpMention]]) -> Dict[str, PlayerSharpScore]:
        """
        Calculate sharp consensus scores from mentions by account.
        
        Args:
            mentions_by_account: Dict mapping account -> list of SharpMentions
            
        Returns:
            Dict mapping player_name -> PlayerSharpScore
        """
        player_data: Dict[str, PlayerSharpScore] = {}
        
        for account, mentions in mentions_by_account.items():
            weight = self.weights.get(account, 0.25)
            
            for mention in mentions:
                player_name = mention.player_name
                
                if player_name not in player_data:
                    player_data[player_name] = PlayerSharpScore(player_name=player_name)
                
                player_data[player_name].mentions.append(mention)
                player_data[player_name].raw_count += 1
                player_data[player_name].consensus_score += weight
        
        # Determine consensus direction and boost
        for player_name, score in player_data.items():
            over_count = sum(1 for m in score.mentions if m.bet_direction == "over" or "over" in m.tweet_text.lower())
            under_count = sum(1 for m in score.mentions if m.bet_direction == "under" or "under" in m.tweet_text.lower())
            
            if over_count > under_count:
                score.sharp_direction = "over"
            elif under_count > over_count:
                score.sharp_direction = "under"
            
            # Calculate confidence boost based on consensus score
            score.confidence_boost = int(score.consensus_score * SHARP_CONSENSUS_BOOST * 10)
            
            # Mark as fade if multiple sharps fading
            fade_count = sum(1 for m in score.mentions if m.bet_direction == "fade")
            if fade_count >= 2:
                score.is_sharp_fade = True
        
        return player_data

# ============================================================
# MAIN SHARP SCANNER CLASS
# ============================================================

class SharpScanner:
    """
    Main scanner for X/Twitter sharp bettors.
    
    Usage:
        scanner = SharpScanner()
        consensus = scanner.scan_sharp_accounts()
        recommendations = scanner.weight_vito_picks(vito_picks, consensus)
    """
    
    def __init__(self, api_key: str = APIFY_API_KEY):
        self.twitter_client = ApifyTwitterClient(api_key)
        self.calculator = SharpConsensusCalculator()
        self.accounts = SHARP_ACCOUNTS
        self.cache: Dict[str, Any] = {}
        self.cache_duration = timedelta(minutes=15)  # Cache for 15 minutes
    
    def _is_cache_valid(self, key: str) -> bool:
        """Check if cache entry is still valid."""
        if key not in self.cache:
            return False
        cached_time = self.cache[key].get("_cached_at")
        if not cached_time:
            return False
        return datetime.now() - cached_time < self.cache_duration
    
    def scan_sharp_accounts(self, max_tweets_per_account: int = 30) -> Dict[str, PlayerSharpScore]:
        """
        Scan all sharp accounts and return consensus.
        
        Args:
            max_tweets_per_account: How many recent tweets to fetch per account
            
        Returns:
            Dict of player_name -> PlayerSharpScore with consensus data
        """
        mentions_by_account: Dict[str, List[SharpMention]] = {acc: [] for acc in self.accounts}
        
        for account in self.accounts:
            # Check cache first
            cache_key = f"tweets_{account}"
            if self._is_cache_valid(cache_key):
                tweets = self.cache[cache_key].get("tweets", [])
                logger.info(f"Using cached {len(tweets)} tweets from @{account}")
            else:
                tweets = self.twitter_client.get_tweets_by_username(account, max_tweets_per_account)
                self.cache[cache_key] = {"tweets": tweets, "_cached_at": datetime.now()}
            
            # Extract mentions from tweets
            extractor = PlayerNameExtractor()
            for tweet in tweets:
                tweet_text = tweet.get("text", "") or tweet.get("fullText", "")
                tweet_url = tweet.get("url", "")
                timestamp_str = tweet.get("createdAt") or tweet.get("timestamp")
                
                try:
                    if isinstance(timestamp_str, str):
                        timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                    else:
                        timestamp = datetime.now()
                except:
                    timestamp = datetime.now()
                
                # Extract player bets
                player_bets = extractor.extract_player_bets(tweet_text)
                
                for player_name, direction in player_bets:
                    mention = SharpMention(
                        player_name=player_name,
                        account=account,
                        tweet_text=tweet_text,
                        tweet_url=tweet_url,
                        timestamp=timestamp,
                        bet_direction=direction
                    )
                    mentions_by_account[account].append(mention)
        
        # Calculate consensus
        consensus = self.calculator.calculate_consensus(mentions_by_account)
        
        # Sort by consensus score
        sorted_consensus = dict(sorted(
            consensus.items(),
            key=lambda x: x[1].consensus_score,
            reverse=True
        ))
        
        return sorted_consensus
    
    def search_sharp_terms(self, terms: List[str] = None) -> List[Dict]:
        """
        Search Twitter for sharp betting terms.
        
        Args:
            terms: List of search terms (default: common prop search terms)
            
        Returns:
            List of matching tweets
        """
        if terms is None:
            terms = [
                "MLB props tonight",
                "NBA player props",
                "NHL player props",
                "sharp bets today",
                "sports betting picks",
            ]
        
        all_tweets = []
        for term in terms:
            cache_key = f"search_{term}"
            if self._is_cache_valid(cache_key):
                tweets = self.cache[cache_key].get("tweets", [])
            else:
                tweets = self.twitter_client.search_tweets(term, max_tweets=50)
                self.cache[cache_key] = {"tweets": tweets, "_cached_at": datetime.now()}
            all_tweets.extend(tweets)
        
        return all_tweets
    
    def get_player_sharp_data(self, player_name: str) -> Optional[PlayerSharpScore]:
        """
        Get sharp consensus data for a specific player.
        
        Args:
            player_name: Name of player to look up
            
        Returns:
            PlayerSharpScore if found, None otherwise
        """
        consensus = self.scan_sharp_accounts()
        
        # Try exact match first
        if player_name in consensus:
            return consensus[player_name]
        
        # Try case-insensitive partial match
        player_lower = player_name.lower()
        for name, score in consensus.items():
            if player_lower in name.lower():
                return score
        
        return None
    
    def weight_vito_picks(self, vito_picks: List[Any], consensus: Dict[str, PlayerSharpScore] = None) -> List[Dict]:
        """
        Weight Vito's picks against sharp consensus.
        
        Args:
            vito_picks: List of PropPick or WinnerPick objects from Vito's report
            consensus: Pre-fetched consensus dict (optional)
            
        Returns:
            List of dicts with pick info + sharp consensus adjustment
        """
        if consensus is None:
            consensus = self.scan_sharp_accounts()
        
        weighted_picks = []
        
        for pick in vito_picks:
            pick_dict = {
                "player": getattr(pick, "player", getattr(pick, "team", "Unknown")),
                "stat_type": getattr(pick, "stat_type", "game"),
                "line": getattr(pick, "line", 0),
                "direction": getattr(pick, "direction", ""),
                "odds": getattr(pick, "odds", -110),
                "original_confidence": getattr(pick, "confidence", 70),
                "sharp_consensus": None,
                "sharp_direction": "",
                "adjusted_confidence": getattr(pick, "confidence", 70),
                "sharp_boost": 0,
                "recommendation": "neutral",
            }
            
            # Find matching sharp data
            player_name = pick_dict["player"]
            sharp_data = None
            
            # Try exact match
            if player_name in consensus:
                sharp_data = consensus[player_name]
            else:
                # Try partial match
                player_lower = player_name.lower()
                for name, data in consensus.items():
                    if player_lower in name.lower() or name.lower() in player_lower:
                        sharp_data = data
                        break
            
            if sharp_data:
                pick_dict["sharp_consensus"] = sharp_data.consensus_score
                pick_dict["sharp_direction"] = sharp_data.sharp_direction
                pick_dict["sharp_boost"] = sharp_data.confidence_boost
                
                # Determine recommendation based on consensus
                vito_direction = pick_dict.get("direction", "").lower()
                
                if sharp_data.is_sharp_fade:
                    pick_dict["recommendation"] = "fade_vito"  # Sharps fading - be cautious
                    pick_dict["adjusted_confidence"] = max(30, pick_dict["original_confidence"] - 15)
                elif sharp_data.sharp_direction == vito_direction:
                    pick_dict["recommendation"] = "sharps_agree"  # Sharps agree with Vito
                    pick_dict["adjusted_confidence"] = min(95, pick_dict["original_confidence"] + sharp_data.confidence_boost)
                elif sharp_data.sharp_direction and vito_direction:
                    pick_dict["recommendation"] = "sharps_disagree"  # Sharps disagree with Vito
                    pick_dict["adjusted_confidence"] = max(40, pick_dict["original_confidence"] - 10)
                    pick_dict["note"] = f"⚠️ Sharps going {sharp_data.sharp_direction}, Vito going {vito_direction}"
            
            weighted_picks.append(pick_dict)
        
        return weighted_picks
    
    def get_top_sharp_picks(self, consensus: Dict[str, PlayerSharpScore] = None, min_consensus: float = 0.3) -> List[Dict]:
        """
        Get top sharp picks based on consensus.
        
        Args:
            consensus: Pre-fetched consensus dict (optional)
            min_consensus: Minimum consensus score to include
            
        Returns:
            List of top sharp picks
        """
        if consensus is None:
            consensus = self.scan_sharp_accounts()
        
        top_picks = []
        for player_name, score in consensus.items():
            if score.consensus_score >= min_consensus:
                top_picks.append({
                    "player": player_name,
                    "sharp_count": score.raw_count,
                    "consensus_score": score.consensus_score,
                    "direction": score.sharp_direction,
                    "confidence_boost": score.confidence_boost,
                    "is_fade": score.is_sharp_fade,
                    "sample_tweets": [
                        {
                            "account": m.account,
                            "text": m.tweet_text[:100] + "..." if len(m.tweet_text) > 100 else m.tweet_text,
                            "url": m.tweet_url
                        }
                        for m in score.mentions[:2]  # First 2 mentions as samples
                    ]
                })
        
        # Sort by consensus score
        top_picks.sort(key=lambda x: x["consensus_score"], reverse=True)
        return top_picks

# ============================================================
# CLI / TESTING
# ============================================================

def main():
    """Test the sharp scanner."""
    print("🍝 Uncle Vito's Sharp Scanner Test")
    print("=" * 50)
    
    scanner = SharpScanner()
    
    # Test 1: Scan sharp accounts
    print("\n📡 Scanning sharp bettor accounts...")
    consensus = scanner.scan_sharp_accounts(max_tweets_per_account=20)
    
    if consensus:
        print(f"\n📊 Found {len(consensus)} players mentioned by sharps:")
        for player, score in list(consensus.items())[:10]:
            print(f"  • {player}: score={score.consensus_score:.2f}, count={score.raw_count}, direction={score.sharp_direction}")
    else:
        print("\n⚠️ No sharp mentions found (Apify API may have failed)")
        print("   Check API key and account validity")
    
    # Test 2: Top sharp picks
    print("\n🎯 Top Sharp Picks:")
    top_picks = scanner.get_top_sharp_picks(consensus, min_consensus=0.25)
    for i, pick in enumerate(top_picks[:5], 1):
        fade_tag = " [FADE]" if pick["is_fade"] else ""
        print(f"  {i}. {pick['player']}{fade_tag}")
        print(f"     Sharps: {pick['sharp_count']} accounts, Score: {pick['consensus_score']:.2f}")
        print(f"     Direction: {pick['direction'] or 'unknown'}")
    
    return consensus

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
