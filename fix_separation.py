with open('/home/ubuntu/.openclaw/workspace/workers/superbot/superbot.py', 'r') as f:
    content = f.read()

# The block to remove starts with "# === OPEN ORDER STRATEGY: Catch MACRO_FADE/PUMP at the open ==="
# and ends just before "# === 12-MIN NO LOCK-IN: Check at 12 min mark"

old_block = """        # === OPEN ORDER STRATEGY: Catch MACRO_FADE/PUMP at the open ===
        # If MACRO_FADE fires with 5+ coins and market just opened, try to get both YES+NO <= $0.15
        if candle_sig and candle_sig.get('signal_type') in ('MACRO_FADE', 'MACRO_PUMP'):
            cluster_coins = candle_sig.get('cluster_coins', [])
            if len(cluster_coins) >= 5:
                sig_timestamp = candle_sig.get('timestamp', '')
                try:
                    sig_dt = datetime.fromisoformat(sig_timestamp.replace('Z','')).replace(tzinfo=None)
                    sig_age = (datetime.utcnow() - sig_dt).total_seconds()
                except:
                    sig_age = 999
                
                # Only try if we haven't tried this exact signal yet
                # Note: sig_age check removed - _place_open_orders has its own market-age check
                # which is the correct metric (market freshness, not signal file age)
                open_order_key = (coin, sig_timestamp)
                if open_order_key not in getattr(self, '_open_order_tried', set()):
                    if not hasattr(self, '_open_order_tried'):
                        self._open_order_tried = set()
                    self._open_order_tried.add(open_order_key)
                    
                    logger.info(f"[{coin}] OPEN ORDER: Fresh {candle_sig.get('signal_type')} with {len(cluster_coins)} coins, age={sig_age:.0f}s - checking open market...")
                    both_filled = self._place_open_orders(coin, markets, candle_sig.get('signal_type', 'MACRO_FADE'))
                    if both_filled:
                        # Open order succeeded - both sides filled cheap, we're hedged for profit
                        logger.info(f"[{coin}] OPEN ORDER: Success! Both sides filled at open. Returning.")
                        return True

        # === 12-MIN NO LOCK-IN:"""

new_block = """        # === TONY_FADE is handled independently by CW (candle_watcher.py) ===
        # CW polls every 5s checking if newly-opened markets have YES_bid or NO_bid <= $0.15
        # If so, places $1 limit order at $0.15 and holds to settlement
        # SB focuses purely on MACRO_FADE and other strategies
        # === 12-MIN NO LOCK-IN:"""

if old_block in content:
    content = content.replace(old_block, new_block)
    print('Replaced open order block with TONY_FADE comment')
else:
    print('ERROR: Block not found exactly')
    # Try to find the approximate location
    idx = content.find('# === OPEN ORDER STRATEGY')
    if idx > 0:
        print(f'Found at position {idx}')
        print('Context:', repr(content[idx:idx+200]))

with open('/home/ubuntu/.openclaw/workspace/workers/superbot/superbot.py', 'w') as f:
    f.write(content)
