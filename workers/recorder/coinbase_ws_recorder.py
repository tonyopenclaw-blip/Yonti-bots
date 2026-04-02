#!/usr/bin/env python3
"""
Coinbase Advanced Trade WebSocket Recorder
Streams real-time price data for multiple crypto pairs and writes to JSONL.
No API key required — uses public market data feed.
"""

import asyncio
import json
import sys
from datetime import datetime
from websockets import connect

# Our coins on Kalshi, mapped to Coinbase product IDs
COINS = {
    "BTC": "BTC-USD",
    "ETH": "ETH-USD",
    "SOL": "SOL-USD",
    "XRP": "XRP-USD",
    "DOGE": "DOGE-USD",
    "BNB": "BNB-USD",
    "HYPE": "HYPE-USD",
    "ADA": "ADA-USD",
}

WS_URL = "wss://advanced-trade-ws.coinbase.com"
OUTPUT_FILE = "/home/ubuntu/.openclaw/workspace/workers/recorder/data/market_data.jsonl"
LOG_FILE = "/home/ubuntu/.openclaw/workspace/workers/recorder/logs/coinbase_ws.log"

product_ids = list(COINS.values())
product_to_coin = {v: k for k, v in COINS.items()}

def log(msg):
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts} | {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def parse_ticker_event(event, ts):
    """Parse a ticker event from the events array."""
    tickers = event.get("tickers", [])
    records = []
    for t in tickers:
        if t.get("type") != "ticker":
            continue
        product_id = t.get("product_id", "")
        coin_key = product_to_coin.get(product_id, product_id)
        records.append({
            "timestamp": ts,
            "coin": coin_key,
            "product_id": product_id,
            "price": float(t.get("price", 0)),
            "bid": float(t.get("best_bid", 0)),
            "ask": float(t.get("best_ask", 0)),
            "volume_24h": float(t.get("volume_24_h", 0)),
            "low_24h": float(t.get("low_24_h", 0)),
            "high_24h": float(t.get("high_24_h", 0)),
            "price_percent_chg_24h": float(t.get("price_percent_chg_24_h", 0)),
        })
    return records

async def record_ticks():
    tick_count = 0
    connect_count = 0

    while True:
        try:
            async with connect(WS_URL, ping_interval=None) as ws:
                connect_count += 1
                log(f"📡 Connected to Coinbase WebSocket (attempt {connect_count})")

                subscribe_msg = {
                    "type": "subscribe",
                    "channel": "ticker",
                    "product_ids": product_ids
                }
                await ws.send(json.dumps(subscribe_msg))
                log(f"📋 Subscribed to: {', '.join(product_ids)}")

                while True:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=30)
                        data = json.loads(msg)

                        channel = data.get("channel", "")
                        if channel != "ticker":
                            continue

                        ts = data.get("timestamp", datetime.utcnow().isoformat() + "Z")
                        events = data.get("events", [])

                        for event in events:
                            records = parse_ticker_event(event, ts)
                            for record in records:
                                with open(OUTPUT_FILE, "a") as f:
                                    f.write(json.dumps(record) + "\n")
                                tick_count += 1

                                if tick_count % 200 == 0:
                                    log(f"📊 {tick_count} ticks | BTC: ${record['price']} | ETH: getting live data...")

                    except asyncio.TimeoutError:
                        continue

        except Exception as e:
            log(f"❌ Connection error: {e}. Reconnecting in 5s...")
            await asyncio.sleep(5)

if __name__ == "__main__":
    log("=" * 60)
    log("🚀 Coinbase WS Recorder starting...")
    log(f"📁 Output: {OUTPUT_FILE}")
    log(f"📋 Coins: {', '.join(product_ids)}")
    log("=" * 60)

    try:
        asyncio.run(record_ticks())
    except KeyboardInterrupt:
        log("🛑 Recorder stopped by user")
        sys.exit(0)
