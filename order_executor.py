import os
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, BalanceAllowanceParams, AssetType
from py_clob_client.order_builder.constants import BUY
from py_clob_client.clob_types import OrderArgs, OrderType
from config_manager import config
from notification_manager import Notifier

# Load environment variables
load_dotenv()

class OrderExecutor:
    def __init__(self):
        self.host = "https://clob.polymarket.com"
        self.chain_id = 137 # Polygon Mainnet
        self.private_key = os.getenv("PRIVATE_KEY")
        self.proxy_address = os.getenv("PROXY_ADDRESS") # Ensure this is in your .env
        self.client = self._connect()

    def _connect(self):
        """Connects to CLOB using Magic Link (Proxy) credentials."""
        if not self.private_key or not self.proxy_address:
            print("❌ Error: Missing PRIVATE_KEY or PROXY_ADDRESS in .env")
            return None

        try:
            print(f"🔌 Connecting to Polymarket via Proxy: {self.proxy_address}...")
            
            # Signature Type 1 = Magic Link / Gnosis Safe / Proxy Wallets
            client = ClobClient(
                self.host, 
                key=self.private_key, 
                chain_id=self.chain_id,
                signature_type=1, 
                funder=self.proxy_address 
            )
            
            # Derive API Keys (L2) from the L1 Signature
            client.set_api_creds(client.create_or_derive_api_creds())
            
            print("✅ Client Connected Successfully.")
            return client
        except Exception as e:
            print(f"❌ Connection failed: {e}")
            return None

    def get_usdc_balance(self):
        """Fetches available USDC collateral."""
        if not self.client:
            return 0.0

        try:
            # We use the params object as required by strict typing
            resp = self.client.get_balance_allowance(
                params=BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
            )
            
            # Support both Object (dot notation) and Dict (bracket notation)
            if hasattr(resp, 'balance'):
                raw = resp.balance
            else:
                raw = resp.get('balance', '0')

            # 6 Decimals for USDC
            balance = int(raw) / 1_000_000
            return balance
        except Exception as e:
            print(f"⚠️ Error checking balance: {e}")
            return 0.0

    def execute_strategy(self, condition_id, token_id, amount_usdc):
        """
        Executes a Limit Order for the specified condition.
        
        Args:
            condition_id (str): The specific market ID.
            token_id (str): "YES" or "NO".
            amount_usdc (float): Amount of cash to bet.
        """
        if not self.client:
            return None

        # 1. SAFETY CHECK: Balance
        balance = self.get_usdc_balance()
        if balance < amount_usdc:
            print(f"❌ Insufficient funds. Have: ${balance}, Need: ${amount_usdc}")
            return None

        print(f"🔍 Analyzing Condition: {condition_id} | Target: {token_id}")

        try:
            # 2. GET TOKEN ID
            # market = self.client.get_market(condition_id)
            # token_id = None
            
            
            # if not token_id:
            #     print(f"❌ Token ID not found for {token_id}")
            #     return None

            # 3. CHECK PRICE (Order Book)
            orderbook = self.client.get_order_book(token_id)
            asks = orderbook.asks
            # print("ORDERS:", orderbook)
            print("SELLERS:", asks)

            if not asks:
                print("⚠️ No sellers available (Market might be empty).")
                return None

            # We buy from the cheapest seller
            all_ask_prices = [float(order.price) for order in asks]
            best_price = min(all_ask_prices)
            print("BEST_PRICE:::", best_price)
            
            # Safety: Don't buy if price is too high (e.g. > 99 cents)
            if best_price > 0.40:
                print(f"⚠️ Price too high ({best_price}). Skipping.")
                return None

            # 4. CALCULATE SIZE (Shares = Cash / Price)
            # Example: $5 / 0.50 = 10 Shares
            size = round(amount_usdc / best_price, 2)
            
            print(f"🚀 PLACING ORDER: Buy {size} shares of {token_id} @ {best_price} (Total: ${amount_usdc})")

            # 5. SEND ORDER
            resp = self.client.create_and_post_order(
                OrderArgs(
                    price=best_price,
                    size=size,
                    side="BUY",
                    token_id = token_id
                )
            )

            stop_loss_price = round(max(0.0, best_price - 0.05), 2)

            if resp and resp.get('success'):
                order_id = resp.get('orderID')
                config.add_monitored_token(token_id, stop_loss_price, size, best_price)
                print(f"✅ SUCCESS! Order placed. ID: {order_id}")
                return order_id
            else:
                print(f"❌ Order failed: {resp.get('errorMsg') or resp}")
                return None

        except Exception as e:
            print(f"❌ Error executing strategy: {e}")
            return None
        
    def get_token_price(self, token_id):
        """
        Fetches the current Order Book for a specific token (YES or NO).
        Returns a dictionary with the best ask (buy price) and best bid (sell price).
        """
        try:
            # 1. Fetch Order Book from CLOB
            # This gets the real-time pending orders, not just the last trade.
            order_book = self.client.get_order_book(token_id)

            # 2. Extract Bids and Asks
            # Asks = Sellers (You buy from them). Sorted Low -> High.
            # Bids = Buyers (You sell to them). Sorted High -> Low.
            asks = order_book.asks
            bids = order_book.bids

            # 3. Get Best Prices (Safely handle empty books)
            best_ask = None
            if asks and len(asks) > 0:
                best_ask = float(asks[0].price) # The cheapest price available to BUY
            
            best_bid = None
            if bids and len(bids) > 0:
                best_bid = float(bids[0].price) # The highest price available to SELL

            # 4. Debug Print (Optional)
            print(f"📊 Price Check [{token_id}]:")
            print(f"   -> Best Ask (Buy Price): {best_ask}")
            print(f"   -> Best Bid (Sell Price): {best_bid}")

            return {
                "best_ask": best_ask,
                "best_bid": best_bid,
                "raw_book": order_book # Returns the full object if needed later
            }

        except Exception as e:
            print(f"❌ Error fetching price for token {token_id}: {e}")
            return None
    
    from py_clob_client.clob_types import OrderArgs, OrderType # <--- Importante

    def place_limit_order(self, token_id, price, size, side): 
        print(f"🎣 Lanzando anzuelo: Comprar {size} acciones a ${price}...")

        try:
            resp = self.client.create_and_post_order(
                OrderArgs(
                    price=price,        # Tu precio deseado (Ej: 0.05)
                    size=size,          # Cuántas acciones
                    side=side,
                    token_id=token_id,
                    
                    # ESTA ES LA CLAVE DE LA LIMIT ORDER:
                    # order_type=OrderType.GTC  # Good Till Canceled (Buena hasta cancelar)
                )
            )

            stop_loss_price = round(max(0.0, price - 0.05), 2)
            
            if resp and resp.get("success"):
                print(f"✅ Orden colocada en el libro. ID: {resp.get('orderID')}")
                # config.update_nested("LIMIT_ORDER_IDs", size, resp.get('orderID'))
                # config.add_monitored_token(token_id, stop_loss_price, size, price)
                print("⏳ Ahora a esperar que alguien te venda...")
                return resp.get('orderID')
            else:
                print(f"❌ Error: {resp.get('errorMsg')}")
                
        except Exception as e:
            print(f"💥 Error crítico: {e}")

    def cancel_specific_order(self, order_id):
        """
        Cancels a single specific order based on its ID.
        """
        try:
            print(f"🗑️ Attempting to cancel order: {order_id}...")
            
            # Execute cancellation
            resp = self.client.cancel(order_id)
            
            # Check if the cancellation was successful
            if resp and resp.get("success"):
                print(f"✅ SUCCESS! Order {order_id} has been cancelled.")
                return True
            else:
                print(f"⚠️ Failed to cancel order. API Response: {resp}")
                return False

        except Exception as e:
            print(f"❌ Error cancelling order {order_id}: {e}")
            return False
        
    def sell_at_best_price(self, token_id, size):
        """
        Simulates a MARKET SELL by setting a low limit price.
        The matching engine will give you the best available price (Bids),
        but this ensures execution even if the price drops slightly.
        """
        print(f"📉 EXECUTING AGGRESSIVE SELL: {size} shares of {token_id}")

        try:
            # 1. Get current best bid just for reference/logging
            book = self.client.get_order_book(token_id)
            if not book.bids:
                print("❌ Market is dead (No buyers). Cannot sell.")
                return None
            
            best_bid = float(book.bids[0].price)
            print(f"ℹ️ Current Best Bid is: {best_bid}")

            # 2. CALCULATE "DUMP" PRICE
            # We set the limit price LOWER than the current bid.
            # Example: If Bid is 0.50, we ask for 0.45.
            # The engine will still sell at 0.50 if available, but allows slippage down to 0.45.
            slippage_tolerance = 0.05 # 5 cents tolerance
            aggressive_price = round(max(0.01, best_bid - slippage_tolerance), 2)

            print(f"🚀 Sending Sell Order @ {aggressive_price} (Crossing the spread)...")

            # 3. SEND ORDER
            resp = self.client.create_and_post_order(
                OrderArgs(
                    price=aggressive_price, 
                    size=size,
                    side="SELL",
                    token_id=token_id,
                    order_type=OrderType.FOK # Fill fully or cancel (prevents partial sells at bad prices)
                )
            )

            if resp and resp.get("success"):
                print(f"✅ SOLD! Order ID: {resp.get('orderID')}")
                return resp.get('orderID')
            else:
                print(f"❌ Sell failed: {resp}")
                return None

        except Exception as e:
            print(f"💥 Error: {e}")
            return None

    def sell_rapidly(self, token_id, size):
            """
            Executes a true MARKET SELL by dumping the tokens at the lowest possible price ($0.01).
            The exchange's matching engine will automatically give the best available bids.
            Skips the order book check to save critical milliseconds.
            """
            print(f"🚨 PANIC SELL INITIATED: Dumping {size} shares of {token_id}")

            try:
                panic_price = 0.01 
                print(f"🚀 Firing aggressive market order to sweep the book...")

                from py_clob_client.clob_types import OrderType, OrderArgs

                # 1. Create the order arguments payload (order_type must NOT be included here)
                order_args = OrderArgs(
                    price=panic_price, 
                    size=size,
                    side="SELL",
                    token_id=token_id
                )

                # 2. Cryptographically sign the order locally
                signed_order = self.client.create_order(order_args)

                # 3. Post the order to the exchange, specifying the FAK type directly to the matching engine
                resp = self.client.post_order(signed_order, OrderType.FAK)

                if resp and resp.get("success"):
                    print(f"✅ SOLD RAPIDLY! Order ID: {resp.get('orderID')}")
                    return resp.get('orderID')
                else:
                    print(f"❌ Rapid sell failed: {resp.get('errorMsg') or resp}")
                    return None

            except Exception as e:
                print(f"💥 Critical Error during panic sell: {e}")
                return None

# Global Instance
OrderExecutor = OrderExecutor()
print("Balance USDC", OrderExecutor.get_usdc_balance())