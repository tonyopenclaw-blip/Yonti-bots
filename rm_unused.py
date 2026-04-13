with open('/home/ubuntu/.openclaw/workspace/workers/superbot/superbot.py', 'r') as f:
    content = f.read()

# Remove the _place_open_orders method entirely
old_method = '''
    def _place_open_orders(self, coin: str, markets: List[Market], signal_type: str) -> bool:
        """
        OPEN ORDER STRATEGY (Tony's edge play):
        When MACRO_FADE/PUMP fires, check if newly opened market has YES and NO both <= $0.15.
        If so, place $1 YES + $1 NO limit orders at $0.15 simultaneously.
        Wait up to 30s for fills. Cancel unfilled.

        This catches reversals at the open - if both sides are cheap, one side will move.

        Args:
            coin: coin symbol (BTC, ETH, etc.)
            markets: list of open Market objects
            signal_type: 'MACRO_FADE' or 'MACRO_PUMP'

        Returns:
            True if both sides filled at <= $0.15, False otherwise
        """
        OPEN_ORDER_MAX_PRICE = 0.15
        OPEN_ORDER_AMOUNT = 1.00  # $1 per side
        OPEN_ORDER_TIMEOUT = 30    # seconds to wait for fills
        OPEN_ORDER_POLL = 5       # poll every 5 seconds

        # Find the market with most time remaining (likely the newly opened one)
        market = None
        max_time = 0
        for m in markets:
            try:
                ttl = m.time_to_expiry_sec()
                if ttl > max_time:
                    max_time = ttl
                    market = m
            except (AttributeError, TypeError):
                continue

        if not market:
            return False

        ticker = market.ticker

        # Check if market just opened (within 60s of now based on market open_time)
        try:
            import re
            open_time_str = getattr(market, 'open_time', None) or ''
            if open_time_str:
                # Parse ISO timestamp
                open_dt = datetime.fromisoformat(open_time_str.replace('Z', '+00:00'))
                open_ts = open_dt.timestamp()
                age = time.time() - open_ts
                if age > 15:
                    logger.debug(f"[{coin}] OPEN ORDER: market age {age:.0f}s > 15s, skipping open-order check")
                    return False
                logger.info(f"[{coin}] OPEN ORDER: market {ticker} is {age:.0f}s old, checking prices...")
        except Exception as e:
            logger.debug(f"[{coin}] OPEN ORDER: couldn't parse market age: {e}")
            # Continue anyway - check prices directly

        # Get current prices
        yes_bid = getattr(market, 'yes_bid', None) or 0
        yes_ask = getattr(market, 'yes_ask', None) or 0
        no_bid = getattr(market, 'no_bid', None) or 0
        no_ask = getattr(market, 'no_ask', None) or 0

        yes_mid = (yes_bid + yes_ask) / 2 if yes_bid and yes_ask else None
        no_mid = (no_bid + no_ask) / 2 if no_bid and no_ask else None

        logger.info(f"[{coin}] OPEN ORDER: YES mid={yes_mid:.4f} NO mid={no_mid:.4f} (max=${OPEN_ORDER_MAX_PRICE:.2f})")

        # Check if both sides are cheap enough
        if yes_mid is None or no_mid is None:
            return False
        if yes_mid > OPEN_ORDER_MAX_PRICE or no_mid > OPEN_ORDER_MAX_PRICE:
            logger.info(f"[{coin}] OPEN ORDER: prices too high (YES={yes_mid:.4f} NO={no_mid:.4f}), skipping")
            return False

        logger.info(f"[{coin}] OPEN ORDER: BOTH SIDES <= ${OPEN_ORDER_MAX_PRICE:.2f}! Placing simultaneous orders...")

        # Place $1 YES and $1 NO limit orders simultaneously
        # Use limit orders at $0.15 (max price we're willing to pay)
        contracts_yes = max(1, int(OPEN_ORDER_AMOUNT / OPEN_ORDER_MAX_PRICE))
        contracts_no = max(1, int(OPEN_ORDER_AMOUNT / OPEN_ORDER_MAX_PRICE))

        # Place YES order
        yes_result = self.api.place_order(
            ticker=ticker,
            side='yes',
            price=OPEN_ORDER_MAX_PRICE,
            amount=OPEN_ORDER_AMOUNT,
            action='buy',
            order_type='limit'
        )

        # Place NO order
        no_result = self.api.place_order(
            ticker=ticker,
            side='no',
            price=OPEN_ORDER_MAX_PRICE,
            amount=OPEN_ORDER_AMOUNT,
            action='buy',
            order_type='limit'
        )

        yes_order_id = yes_result.get('order', {}).get('order_id') if 'order' in yes_result else None
        no_order_id = no_result.get('order', {}).get('order_id') if 'order' in no_result else None

        logger.info(f"[{coin}] OPEN ORDER: YES order placed: {yes_result.get('order',{})}")
        logger.info(f"[{coin}] OPEN ORDER: NO order placed: {no_result.get('order',{})}")

        if not yes_order_id and not no_order_id:
            logger.warning(f"[{coin}] OPEN ORDER: both orders failed to place!")
            return False

        # Wait for fills
        filled_yes = False
        filled_no = False
        fills_yes = 0
        fills_no = 0

        for i in range(OPEN_ORDER_TIMEOUT // OPEN_ORDER_POLL):
            time.sleep(OPEN_ORDER_POLL)

            # Check YES order
            if yes_order_id and not filled_yes:
                status = self.api._get(f"/portfolio/orders/{yes_order_id}")
                order = status.get('order', {})
                order_status = order.get('status', '')
                if order_status in ('executed', 'filled', 'complete'):
                    fills_yes = float(order.get('fill_count_fp', 0))
                    filled_yes = True
                    logger.info(f"[{coin}] OPEN ORDER: YES FILLED! {fills_yes} contracts @ ${OPEN_ORDER_MAX_PRICE:.2f}")

            # Check NO order
            if no_order_id and not filled_no:
                status = self.api._get(f"/portfolio/orders/{no_order_id}")
                order = status.get('order', {})
                order_status = order.get('status', '')
                if order_status in ('executed', 'filled', 'complete'):
                    fills_no = float(order.get('fill_count_fp', 0))
                    filled_no = True
                    logger.info(f"[{coin}] OPEN ORDER: NO FILLED! {fills_no} contracts @ ${OPEN_ORDER_MAX_PRICE:.2f}")

            if filled_yes and filled_no:
                logger.info(f"[{coin}] OPEN ORDER: BOTH SIDES FILLED! Profit locked in regardless of direction.")
                break

        # Cancel unfilled orders
        if yes_order_id and not filled_yes:
            self.api.cancel_order(yes_order_id)
            logger.info(f"[{coin}] OPEN ORDER: YES order cancelled (not filled)")
        if no_order_id and not filled_no:
            self.api.cancel_order(no_order_id)
            logger.info(f"[{coin}] OPEN ORDER: NO order cancelled (not filled)")

        # Result: both filled at <= $0.15 = success
        if filled_yes and filled_no:
            logger.info(f"[{coin}] OPEN ORDER SUCCESS: {signal_type} caught at open for ${OPEN_ORDER_AMOUNT*2:.2f} total")
            return True
        else:
            logger.info(f"[{coin}] OPEN ORDER: partial fill YES={filled_yes} NO={filled_no}, continuing with normal execution")
            return False

'''

if old_method in content:
    content = content.replace(old_method, '')
    print('Removed _place_open_orders method')
else:
    print('ERROR: Method not found')
    idx = content.find('def _place_open_orders')
    if idx > 0:
        print(f'Found at {idx}')

with open('/home/ubuntu/.openclaw/workspace/workers/superbot/superbot.py', 'w') as f:
    f.write(content)
