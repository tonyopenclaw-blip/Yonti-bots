import json
import time
import requests
from datetime import datetime, timezone
import jwt

PRIVATE_KEY_FILE = "kalshi_private_key.pem"
KALSHI_ACCESS_KEY_ID = "12920c50-132b-4237-9575-7d5958a74830"
KALSHI_API_URL = "https://api.elections.kalshi.com"

with open(PRIVATE_KEY_FILE) as f:
    private_key = f.read()

# Generate JWT
payload = {
    "iss": KALSHI_ACCESS_KEY_ID,
    "iat": int(time.time()),
    "exp": int(time.time()) + 60
}
token = jwt.encode(payload, private_key, algorithm="RS256")
print(f"Token generated: {token[:50]}...")

# Test balance API
headers = {"Authorization": f"Bearer {token}"}
resp = requests.get(f"{KALSHI_API_URL}/trade-api/v2/portfolio/balance", headers=headers, timeout=10)
print(f"Status: {resp.status_code}")
print(f"Response: {resp.text[:200]}")
