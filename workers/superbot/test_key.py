#!/usr/bin/env python3
"""Test all Kalshi API keys to see which one is valid."""
import json, time, requests, jwt, sys

PRIVATE_KEY_FILE = "kalshi_private_key.pem"
BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

with open(PRIVATE_KEY_FILE) as f:
    private_key = f.read()

# Test multiple access keys
ACCESS_KEYS = [
    ("a0235926-8b18-4f93-81ab-e4383ba61ec9", "Real Superbot 3"),
    ("12920c50-132b-4237-9575-7d5958a74830", "Cashsync"),
    ("f085af89-0df7-44e2-9bb3-4af0435cbfda", "Real Superbot 2"),
    ("e275fa0a-90e0-4eaa-9fb1-d25c9f8ed804", "RealSuperbot"),
]

def make_request(access_key_id):
    """Make authenticated request using raw JWT."""
    payload = {
        "iss": access_key_id,
        "iat": int(time.time()),
        "exp": int(time.time()) + 60
    }
    token = jwt.encode(payload, private_key, algorithm="RS256")
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(f"{BASE_URL}/portfolio/balance", headers=headers, timeout=10)
    return resp.status_code, resp.text[:200]

for key_id, name in ACCESS_KEYS:
    try:
        status, body = make_request(key_id)
        print(f"{name} ({key_id[:8]}...): {status} -> {body}")
    except Exception as e:
        print(f"{name} ({key_id[:8]}...): ERROR -> {e}")
