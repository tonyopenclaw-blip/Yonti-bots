"""Fix the 4 critical bleeding issues identified by Nerd."""

# ============================================================
# FIX 1: Raise MACRO_FADE cluster threshold from 5 to 7
# ============================================================
with open('/home/ubuntu/.openclaw/workspace/workers/superbot/candle_watcher.py') as f:
    content = f.read()

old = 'MACRO_MIN_CLUSTER = 5     # Minimum coins to trigger macro fade (raised from 3 — 3-4 coin clusters 0W/4L vs 7-8 coin clusters 9W/0L)'
new = 'MACRO_MIN_CLUSTER = 7     # Minimum coins to trigger macro fade (raised from 5 — 5-6 coin clusters 0% WR, 7+ clusters 9W/0L)'

if old in content:
    content = content.replace(old, new)
    print("FIX 1: Raised MACRO_MIN_CLUSTER to 7")
else:
    print("ERROR: MACRO_MIN_CLUSTER pattern not found")

with open('/home/ubuntu/.openclaw/workspace/workers/superbot/candle_watcher.py', 'w') as f:
    f.write(content)

# ============================================================
# FIX 2: No entries in last 3 minutes — add gate in _execute_candle_signal
# ============================================================
with open('/home/ubuntu/.openclaw/workspace/workers/superbot/superbot.py') as f:
    content = f.read()

# Find the time_left < 60 skip and add a 3-min gate after it
old = '''            if time_left < 60:
                continue

            mid = (market.yes_bid + market.yes_ask) / 2'''

new = '''            if time_left < 60:
                continue

            # NERD FIX: No entries in last 3 minutes — too close to expiry
            if time_left < 180:
                logger.info(f"[{coin}] ENTRY SKIP: only {time_left}s left (< 180s minimum)")
                continue

            mid = (market.yes_bid + market.yes_ask) / 2'''

if old in content:
    content = content.replace(old, new)
    print("FIX 2: Added 180s minimum time-to-expiry gate")
else:
    print("ERROR: time_left < 60 pattern not found")

# ============================================================
# FIX 3: Cut-loss exception when <180s to expiry
# ============================================================
old = '''            # CUT-LOSS: If price <= $0.10 AND time_remaining <= 7.5 min, close entire position immediately
            # Nerd fix: raised from $0.20 to $0.10 - $0.20 was cutting winners prematurely (33% cut-loss rate, 0% win rate)
            # EXCEPTION: candle-duration positions hold to expiry - they would have won (BNB, SOL, HYPE, BTC, XRP all won)
            elif mid_price <= 0.10 and time_left <= 450 and not position.is_candle_duration:
                entry_price = position.avg_price if position.avg_price > 0 else position.entry_price
                logger.warning(f"CUT LOSS: [{self.coin}] {position.side.upper()} {ticker} exited at ${mid_price:.4f} (was ${entry_price:.4f} entry, time_left={time_left}s)")
                self._close_position(ticker, "cut_loss_30", mid_price, side=side)
                positions_changed = True
                continue'''

new = '''            # CUT-LOSS: If price <= $0.10 AND 3min < time_remaining <= 7.5 min, close entire position immediately
            # Nerd fix: Do NOT cut when < 180s to expiry — let near-settlement positions hold to settle
            # All 6 trades that hit cut_loss_30 would have WON if held to settlement (market settled at ~$0)
            elif mid_price <= 0.10 and time_left <= 450 and time_left > 180 and not position.is_candle_duration:
                entry_price = position.avg_price if position.avg_price > 0 else position.entry_price
                logger.warning(f"CUT LOSS: [{self.coin}] {position.side.upper()} {ticker} exited at ${mid_price:.4f} (was ${entry_price:.4f} entry, time_left={time_left}s)")
                self._close_position(ticker, "cut_loss_30", mid_price, side=side)
                positions_changed = True
                continue'''

if old in content:
    content = content.replace(old, new)
    print("FIX 3: Cut-loss now skips when < 180s to expiry")
else:
    print("ERROR: cut_loss pattern not found")

# ============================================================
# FIX 4: 30-second signal max age for MACRO_FADE signals
# Add age check when reading signal from file
# ============================================================
old = '''        signal_file = get_candle_signal_file(coin)
        if not signal_file.exists():
            return None
        try:
            with open(signal_file, "r") as f:
                signal_data = json.load(f)
            sig_timestamp = signal_data.get("timestamp", "")'''

new = '''        signal_file = get_candle_signal_file(coin)
        if not signal_file.exists():
            return None
        try:
            with open(signal_file, "r") as f:
                signal_data = json.load(f)
            sig_timestamp = signal_data.get("timestamp", "")

            # NERD FIX: Reject MACRO_FADE signals older than 30 seconds
            # Signal was firing at 17:14, executing at 17:45 (31 min old) — completely stale
            signal_type = signal_data.get("signal_type", "CANDLE")
            if signal_type == "MACRO_FADE" and sig_timestamp:
                try:
                    sig_time = datetime.fromisoformat(sig_timestamp.replace("Z", "+00:00"))
                    age_sec = (datetime.now(datetime.timezone.utc).replace(tzinfo=None) - sig_time.replace(tzinfo=None)).total_seconds()
                    if age_sec > 30:
                        logger.info(f"[{coin}] MACRO_FADE SKIP: signal age {age_sec:.0f}s > 30s (stale)")
                        signal_file.unlink()
                        return None
                except Exception:
                    pass'''

if old in content:
    content = content.replace(old, new)
    print("FIX 4: Added 30-second max age check for MACRO_FADE signals")
else:
    print("ERROR: signal_file read pattern not found")

with open('/home/ubuntu/.openclaw/workspace/workers/superbot/superbot.py', 'w') as f:
    f.write(content)

print("\nAll fixes applied.")
