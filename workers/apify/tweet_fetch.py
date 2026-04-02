#!/usr/bin/env python3
"""
Fetch tweets using Apify X Scraper.
Usage: python3 tweet_fetch.py <tweet_url> [tweet_url...]

Example:
    python3 tweet_fetch.py https://x.com/w1nklerr/status/2039441440296829219
"""

import sys
import requests
import json
import time

APIFY_TOKEN = "apify_api_sK4vzx6r1hzexr7TA2muKebeQWqChT2psmmB"
ACTOR_ID = "xtdata~twitter-x-scraper"

def start_run(start_urls: list, max_items: int = 10):
    """Start an Apify actor run."""
    url = f"https://api.apify.com/v2/acts/{ACTOR_ID}/runs"
    params = {"token": APIFY_TOKEN}
    payload = {
        "startUrls": start_urls,
        "maxItems": max_items,
        "tweetLanguage": "en"
    }
    response = requests.post(url, params=params, json=payload)
    response.raise_for_status()
    return response.json()["data"]

def get_run_dataset(run_id: str):
    """Get dataset ID from a run."""
    url = f"https://api.apify.com/v2/acts/{ACTOR_ID}/runs/{run_id}"
    params = {"token": APIFY_TOKEN}
    response = requests.get(url, params=params)
    response.raise_for_status()
    return response.json()["data"].get("defaultDatasetId")

def fetch_dataset_items(dataset_id: str):
    """Fetch items from a dataset."""
    url = f"https://api.apify.com/v2/datasets/{dataset_id}/items"
    params = {"token": APIFY_TOKEN, "clean": "true"}
    response = requests.get(url, params=params)
    response.raise_for_status()
    return response.json()

def fetch_tweets(tweet_urls: list, wait_sec: int = 15):
    """Fetch tweets by URLs."""
    print(f"🚀 Starting scrape for {len(tweet_urls)} URL(s)...")
    run = start_run(tweet_urls)
    run_id = run["id"]
    print(f"   Run ID: {run_id}")

    # Poll until done
    status_url = f"https://api.apify.com/v2/acts/{ACTOR_ID}/runs/{run_id}"
    params = {"token": APIFY_TOKEN}

    for i in range(wait_sec):
        time.sleep(1)
        resp = requests.get(status_url, params=params)
        status = resp.json()["data"]["status"]
        if status == "SUCCEEDED":
            break
        elif status == "FAILED":
            print(f"   ❌ Run failed!")
            return []
        print(f"   ⏳ Status: {status} ({i+1}s)")

    dataset_id = run.get("defaultDatasetId") or get_run_dataset(run_id)
    if not dataset_id:
        print("❌ Could not get dataset ID")
        return []

    items = fetch_dataset_items(dataset_id)
    print(f"✅ Got {len(items)} tweet(s)")
    return items

def format_tweet(item: dict) -> str:
    """Format a tweet for display."""
    text = item.get("full_text", "[no text]")
    author = item.get("author", {})
    name = author.get("name", "unknown")
    handle = author.get("screen_name", "")
    created = item.get("created_at", "")
    likes = item.get("favorite_count", 0)
    rts = item.get("retweet_count", 0)
    url = item.get("url", "")

    return f"""
═══════════════════════════════════════
👤 {name} (@{handle})
📅 {created}
❤ {likes} | 🔁 {rts}
🔗 {url}
───────────────────────────────────────
{text}
═══════════════════════════════════════"""

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    urls = sys.argv[1:]
    tweets = fetch_tweets(urls)

    for tweet in tweets:
        print(format_tweet(tweet))
