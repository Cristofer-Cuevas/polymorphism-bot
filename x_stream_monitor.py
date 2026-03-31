import asyncio
import aiohttp
import json
from notification_manager import Notifier
from twilio_caller import call_alert

class XStreamManager:
    def __init__(self, bearer_token: str, sell_trigger, buy_trigger, call_check=None, call_disable=None):
        self.bearer_token = bearer_token
        self.headers = {"Authorization": f"Bearer {self.bearer_token}"}
        self.rules_url = "https://api.twitter.com/2/tweets/search/stream/rules"

        # --- CRITICAL UPDATE ---
        # We append query parameters to force the API to send reference and author data
        self.stream_url = "https://api.twitter.com/2/tweets/search/stream?tweet.fields=referenced_tweets,in_reply_to_user_id,author_id"

        self.sell_trigger = sell_trigger
        self.buy_trigger = buy_trigger

        # Elon Musk's official, static X account ID
        self.call_check = call_check
        self.call_disable = call_disable
        self.elon_id = "44196397"

    async def setup_rules(self, session: aiohttp.ClientSession):
        """Configures the streaming rules. Instantly catches 429 errors to trigger the Circuit Breaker."""
        async with session.get(self.rules_url, headers=self.headers) as response:
            response.raise_for_status() 
            data = await response.json()
            
            if "data" in data:
                rule_ids = [rule["id"] for rule in data["data"]]
                payload = {"delete": {"ids": rule_ids}}
                
                async with session.post(self.rules_url, headers=self.headers, json=payload) as del_resp:
                    del_resp.raise_for_status()
                print("🧹 Cleared old X API rules.")

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
            try:
                print("⚙️ Initializing X API Rules...")
                await self.setup_rules(session)
            except aiohttp.ClientResponseError as e:
                if e.status == 429:
                    print("🛑 [CIRCUIT BREAKER] 429 hit during setup. Sleeping 16 minutes...")
                    Notifier._send("🛑 X API Rate Limit Hit during setup. Pausing for 16 minutes.")
                    await asyncio.sleep(960) 
                else:
                    print(f"⚠️ Setup HTTP Error: {e.status}")
            except Exception as e:
                print(f"⚠️ Setup Network Error: {e}")

            while True:
                try:
                    print("📡 Connecting to X Filtered Stream...")
                    async with session.get(self.stream_url, headers=self.headers) as response:
                        response.raise_for_status()
                        
                        backoff_time = 3
                        print("🟢 Connected to X! Waiting for a tweet...")
                        Notifier._send("🟢 Connected to X! Monitoring @elonmusk for new tweets...")
                        
                        async for line in response.content:
                            clean_line = line.strip()
                            if not clean_line:
                                continue
                                
                            try:
                                tweet_data = json.loads(clean_line)
                                data = tweet_data.get('data', {})
                                tweet_text = data.get('text', 'No text')
                                
                                # --- PARSING METADATA ---
                                referenced_tweets = data.get('referenced_tweets', [])
                                in_reply_to = data.get('in_reply_to_user_id')
                                
                                # Default assumption
                                tweet_category = "Original Post" 
                                
                                # --- CLASSIFICATION LOGIC ---
                                if referenced_tweets:
                                    for ref in referenced_tweets:
                                        if ref.get('type') == 'retweeted':
                                            tweet_category = "Retweet"
                                            break
                                        elif ref.get('type') == 'replied_to':
                                            if in_reply_to == self.elon_id:
                                                tweet_category = "Self-Reply"
                                            else:
                                                tweet_category = "Reply to Someone Else"
                                            break
                                        elif ref.get('type') == 'quoted':
                                            tweet_category = "Quote Tweet"
                                            break

                                print(f"🚨 [{tweet_category.upper()}] DETECTED: {tweet_text}")
                                await asyncio.to_thread(Notifier._send, f"🚨 [{tweet_category.upper()}] DETECTED")

                                # Sell trigger: fires on all tweet types except Self-Reply
                                if tweet_category in ("Original Post", "Reply to Someone Else", "Retweet", "Quote Tweet"):
                                    asyncio.create_task(self.sell_trigger())

                                # Buy trigger + phone call: fires on Original Post, Retweet, Quote Tweet
                                if tweet_category in ("Original Post", "Retweet", "Quote Tweet"):
                                    asyncio.create_task(self.buy_trigger())
                                    if self.call_check and self.call_check():
                                        await asyncio.to_thread(call_alert, tweet_category)
                                        if self.call_disable:
                                            self.call_disable()
                                
                            except json.JSONDecodeError as e:
                                print(f"⚠️ JSON Parse Error on valid line: {e}")
                                
                except aiohttp.ClientResponseError as e:
                    if e.status == 429:
                        print("\n🛑 [CIRCUIT BREAKER] 429 Too Many Requests detected!")
                        print("⏳ X API enforced a strict timeout. Sleeping for 16 minutes...")
                        Notifier._send("⚠️ X API Rate Limit Hit: 429 Too Many Requests. Activating Circuit Breaker for 16 minutes.")
                        
                        await asyncio.sleep(960)
                        backoff_time = 3
                    else:
                        print(f"⚠️ HTTP Error: {e.status}")
                        print(f"⏳ Backing off for {backoff_time} seconds...")
                        await asyncio.sleep(backoff_time)
                        backoff_time = min(backoff_time * 2, 60)
                        
                except Exception as e:
                    print(f"⚠️ Network/Stream Error: {e}")
                    print(f"⏳ Backing off for {backoff_time} seconds...")
                    Notifier._send(f"⚠️ Network/Stream Error: {e}")
                    await asyncio.sleep(backoff_time)
                    backoff_time = min(backoff_time * 2, 60)