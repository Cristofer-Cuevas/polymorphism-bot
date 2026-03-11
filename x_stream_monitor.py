import asyncio
import aiohttp
import json
from notification_manager import Notifier

class XStreamManager:
    def __init__(self, bearer_token: str, trigger_function):
        self.bearer_token = bearer_token
        self.headers = {"Authorization": f"Bearer {self.bearer_token}"}
        self.rules_url = "https://api.twitter.com/2/tweets/search/stream/rules"
        self.stream_url = "https://api.twitter.com/2/tweets/search/stream"
        
        self.trigger_function = trigger_function

    async def setup_rules(self, session: aiohttp.ClientSession):
        """Configures the streaming rules. Instantly catches 429 errors to trigger the Circuit Breaker."""
        
        # 1. Fetch current rules
        async with session.get(self.rules_url, headers=self.headers) as response:
            # raise_for_status() acts as a tripwire. If the response is 429, 503, etc., 
            # it instantly aborts and sends the error to the main loop below.
            response.raise_for_status() 
            data = await response.json()
            
            if "data" in data:
                rule_ids = [rule["id"] for rule in data["data"]]
                payload = {"delete": {"ids": rule_ids}}
                
                # 2. Delete old rules
                async with session.post(self.rules_url, headers=self.headers, json=payload) as del_resp:
                    del_resp.raise_for_status()
                print("🧹 Cleared old X API rules.")

        # 3. Apply new rules
        new_rule = {"add": [{"value": "from:elonmusk", "tag": "any_elon_activity"}]}
        async with session.post(self.rules_url, headers=self.headers, json=new_rule) as post_resp:
            post_resp.raise_for_status()
        print("✅ X API Rules set: Strictly monitoring @elonmusk.")

    async def start_listening(self):
        """
        Main connection loop equipped with a hard 16-minute Circuit Breaker.
        Sets rules ONLY ONCE outside the loop to save API limits.
        """
        timeout = aiohttp.ClientTimeout(total=None)
        backoff_time = 3 
        
        async with aiohttp.ClientSession(timeout=timeout) as session:
            
            # 1. SETUP RULES ONCE BEFORE THE LOOP
            try:
                print("⚙️ Initializing X API Rules...")
                await self.setup_rules(session)
            except aiohttp.ClientResponseError as e:
                if e.status == 429:
                    print("🛑 [CIRCUIT BREAKER] 429 hit during setup. Sleeping 16 minutes...")
                    Notifier._send("🛑 X API Rate Limit Hit during setup. Pausing for 16 minutes.")
                    await asyncio.sleep(960) # 16 mins to clear the rolling window
                else:
                    print(f"⚠️ Setup HTTP Error: {e.status}")
            except Exception as e:
                print(f"⚠️ Setup Network Error: {e}")

            # 2. THE INFINITE LISTENING LOOP
            while True:
                try:
                    print("📡 Connecting to X Filtered Stream...")
                    async with session.get(self.stream_url, headers=self.headers) as response:
                        response.raise_for_status()
                        
                        # Reset the backoff timer only on successful connection
                        backoff_time = 3
                        print("🟢 Connected to X! Waiting for a tweet...")
                        Notifier._send("🟢 Connected to X! Monitoring @elonmusk for new tweets...")
                        
                        async for line in response.content:
                            clean_line = line.strip()
                            if not clean_line:
                                continue
                                
                            try:
                                tweet_data = json.loads(clean_line)
                                tweet_text = tweet_data.get('data', {}).get('text', 'No text')
                                print(f"🚨 TWEET DETECTED: {tweet_text}")
                                Notifier._send(f"🚨 TWEET DETECTED")
                                
                                asyncio.create_task(self.trigger_function())
                            except json.JSONDecodeError as e:
                                print(f"⚠️ JSON Parse Error on valid line: {e}")
                                
                except aiohttp.ClientResponseError as e:
                    # --- THE CIRCUIT BREAKER ---
                    if e.status == 429:
                        print("\n🛑 [CIRCUIT BREAKER] 429 Too Many Requests detected!")
                        print("⏳ X API enforced a strict timeout. Sleeping for 16 minutes...")
                        Notifier._send("⚠️ X API Rate Limit Hit: 429 Too Many Requests. Activating Circuit Breaker for 16 minutes.")
                        
                        await asyncio.sleep(960) # Force a hard sleep for exactly 16 minutes
                        backoff_time = 3 # Reset backoff time to try again fresh
                    else:
                        print(f"⚠️ HTTP Error: {e.status}")
                        print(f"⏳ Backing off for {backoff_time} seconds...")
                        await asyncio.sleep(backoff_time)
                        backoff_time = min(backoff_time * 2, 60)
                        
                except Exception as e:
                    # Standard network errors (like sudden WiFi drops or 503s)
                    print(f"⚠️ Network/Stream Error: {e}")
                    print(f"⏳ Backing off for {backoff_time} seconds...")
                    Notifier._send(f"⚠️ Network/Stream Error: {e}")
                    await asyncio.sleep(backoff_time)
                    backoff_time = min(backoff_time * 2, 60)