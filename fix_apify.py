"""Fix orphaned try/except blocks in sharp_scanner.py after Apify key rotation change."""

with open('/home/ubuntu/.openclaw/workspace/workers/uncle_vito/sharp_scanner.py', 'r') as f:
    content = f.read()

# Fix get_tweets_by_username - remove orphaned code after return []
old_get_tweets = """        if not response or response.status_code not in (200, 201):
            logger.warning(f"Apify start run failed for @{username}: {response.status_code if response else 'no response'}")
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
            return []"""

new_get_tweets = """        if not response or response.status_code not in (200, 201):
            logger.warning(f"Apify start run failed for @{username}: {response.status_code if response else 'no response'}")
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
            return []"""

if old_get_tweets in content:
    content = content.replace(old_get_tweets, new_get_tweets)
    print("Fixed get_tweets_by_username")
else:
    print("ERROR: get_tweets_by_username pattern not found")

# Fix search_tweets - same issue
old_search = """        if not response or response.status_code not in (200, 201):
            logger.warning(f"Apify search failed for '{query}': {response.status_code if response else 'no response'}")
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
            return []"""

new_search = """        if not response or response.status_code not in (200, 201):
            logger.warning(f"Apify search failed for '{query}': {response.status_code if response else 'no response'}")
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
        return []"""

if old_search in content:
    content = content.replace(old_search, new_search)
    print("Fixed search_tweets")
else:
    print("ERROR: search_tweets pattern not found")

with open('/home/ubuntu/.openclaw/workspace/workers/uncle_vito/sharp_scanner.py', 'w') as f:
    f.write(content)
