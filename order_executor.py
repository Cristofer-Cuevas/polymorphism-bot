import os
import time
import requests
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType, BalanceAllowanceParams, AssetType
from config_manager import config
from notification_manager import Notifier
from web3 import Web3
from eth_account import Account
from eth_account.messages import encode_defunct
from eth_abi.packed import encode_packed
from eth_utils import keccak

# Load environment variables
load_dotenv()

# NegRisk Adapter contract on Polygon
NEG_RISK_ADAPTER_ADDRESS = "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296"
CTF_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"

# Polymarket Relayer config (for gasless on-chain txs through proxy)
RELAYER_URL = "https://relayer-v2.polymarket.com"
PROXY_FACTORY = "0xaB45c5A4B0c941a2F231C04C3f49182e1A254052"
RELAY_HUB = "0xD216153c06E857cD7f72665E0aF1d7D82172F494"

NEG_RISK_ADAPTER_ABI = [
    {
        "type": "function",
        "name": "convertPositions",
        "inputs": [
            {"name": "_marketId", "type": "bytes32"},
            {"name": "_indexSet", "type": "uint256"},
            {"name": "_amount", "type": "uint256"}
        ],
        "outputs": [],
        "stateMutability": "nonpayable"
    }
]

PROXY_ABI = [
    {
        "type": "function",
        "name": "proxy",
        "inputs": [
            {
                "name": "calls",
                "type": "tuple[]",
                "components": [
                    {"name": "typeCode", "type": "uint8"},
                    {"name": "to", "type": "address"},
                    {"name": "value", "type": "uint256"},
                    {"name": "data", "type": "bytes"}
                ]
            }
        ],
        "outputs": [{"name": "returnValues", "type": "bytes[]"}],
        "stateMutability": "payable"
    }
]

CTF_ABI = [
    {
        "type": "function",
        "name": "isApprovedForAll",
        "inputs": [
            {"name": "_owner", "type": "address"},
            {"name": "_operator", "type": "address"}
        ],
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view"
    },
    {
        "type": "function",
        "name": "setApprovalForAll",
        "inputs": [
            {"name": "_operator", "type": "address"},
            {"name": "_approved", "type": "bool"}
        ],
        "outputs": [],
        "stateMutability": "nonpayable"
    }
]

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
            orderbook = self.client.get_order_book(token_id)
            asks = orderbook.asks

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
    
    def place_limit_order(self, token_id, price, size, side):
        print(f"🎣 Lanzando anzuelo: Comprar {size} acciones a ${price}...")

        try:
            resp = self.client.create_and_post_order(
                OrderArgs(
                    price=price,
                    size=size,
                    side=side,
                    token_id=token_id,
                )
            )

            if resp and resp.get("success"):
                print(f"✅ Order placed. ID: {resp.get('orderID')}")
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

    def buy_and_convert(self, no_token_id, neg_risk_market_id, condition_id, price, size):
        """
        Buys No on the most unlikely bracket, then converts No tokens
        to Yes on all other brackets via the NegRisk Adapter (on-chain).
        """
        if not self.client:
            print("❌ Client not connected.")
            return None

        try:
            print(f"🎯 Buying {size} No shares @ ${price} (FOK - immediate fill)...")

            # 1. Buy No on the most unlikely bracket — FOK ensures instant fill or cancel
            order = self.client.create_order(OrderArgs(
                price=price,
                size=size,
                side="BUY",
                token_id=no_token_id
            ))
            resp = self.client.post_order(order, OrderType.FOK)

            if not resp or not resp.get("success"):
                print(f"❌ Buy No failed: {resp.get('errorMsg') if resp else 'No response'}")
                return None

            order_id = resp.get("orderID")
            print(f"✅ No shares bought instantly. Order ID: {order_id}")

            # 3. Convert No tokens to Yes on all other brackets (on-chain)
            print(f"🔄 Converting {size} No tokens via NegRisk Adapter...")
            self._convert_positions_onchain(neg_risk_market_id, condition_id, size)
            print(f"✅ Conversion complete!")

            return order_id

        except Exception as e:
            print(f"💥 Error in buy_and_convert: {e}")
            return None

    def buy_yes_direct(self, yes_token_id, price, size):
        """
        Buys YES shares directly on a specific bracket via FOK order.
        No conversion — straight YES purchase.
        """
        if not self.client:
            print("❌ Client not connected.")
            return None

        try:
            print(f"🎯 Buying {size} Yes shares @ ${price} (FOK - immediate fill)...")

            order = self.client.create_order(OrderArgs(
                price=price,
                size=size,
                side="BUY",
                token_id=yes_token_id
            ))
            resp = self.client.post_order(order, OrderType.FOK)

            if not resp or not resp.get("success"):
                print(f"❌ Buy Yes failed: {resp.get('errorMsg') if resp else 'No response'}")
                return None

            order_id = resp.get("orderID")
            print(f"✅ Yes shares bought instantly. Order ID: {order_id}")
            return order_id

        except Exception as e:
            print(f"💥 Error in buy_yes_direct: {e}")
            return None

    def _get_web3(self):
        """Returns a Web3 instance connected to Polygon (PoA chain)."""
        from web3.middleware import ExtraDataToPOAMiddleware
        rpc_url = os.getenv("POLYGON_RPC_URL", "https://polygon-rpc.com")
        w3 = Web3(Web3.HTTPProvider(rpc_url))
        w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        return w3

    def _exec_via_relayer(self, to_address, calldata_hex):
        """
        Executes an on-chain call through Polymarket's Relayer API (gasless).
        The relayer submits the tx through the proxy wallet on our behalf.
        Uses the PROXY transaction type with RelayHub signing.
        """
        relayer_api_key = os.getenv("RELAYER_API_KEY")
        if not relayer_api_key:
            raise Exception("RELAYER_API_KEY not set in .env")

        eoa = Account.from_key(self.private_key).address
        proxy_addr = Web3.to_checksum_address(self.proxy_address)

        # 1. Get relay payload (relay address + nonce)
        rp = requests.get(
            f"{RELAYER_URL}/relay-payload",
            params={"address": eoa, "type": "PROXY"}
        ).json()
        relay_address = rp["address"]
        nonce = rp["nonce"]
        print(f"📋 Relayer nonce: {nonce}, relay: {relay_address}")

        # 2. Encode the proxy(ProxyCall[]) calldata
        w3 = Web3()
        proxy_contract = w3.eth.contract(
            address=proxy_addr,
            abi=PROXY_ABI
        )
        calldata_bytes = bytes.fromhex(calldata_hex[2:] if calldata_hex.startswith("0x") else calldata_hex)
        calls = [(1, Web3.to_checksum_address(to_address), 0, calldata_bytes)]
        raw = proxy_contract.functions.proxy(calls)._encode_transaction_data()
        encoded_data = raw if isinstance(raw, str) and raw.startswith("0x") else "0x" + (raw.hex() if isinstance(raw, bytes) else raw)

        # 3. Create struct hash: keccak256(concat("rlx:", from, to, data, txFee, gasPrice, gasLimit, nonce, relayHub, relay))
        gas_limit = "6000000"
        gas_price = "0"
        relayer_fee = "0"

        to_field = Web3.to_checksum_address(PROXY_FACTORY)

        data_to_hash = (
            b"rlx:"
            + bytes.fromhex(eoa[2:])
            + bytes.fromhex(to_field[2:])
            + bytes.fromhex(encoded_data[2:])
            + int(relayer_fee).to_bytes(32, "big")
            + int(gas_price).to_bytes(32, "big")
            + int(gas_limit).to_bytes(32, "big")
            + int(nonce).to_bytes(32, "big")
            + bytes.fromhex(RELAY_HUB[2:])
            + bytes.fromhex(relay_address[2:])
        )
        struct_hash = keccak(data_to_hash)

        # 4. Sign with EIP-191 personal sign
        msg = encode_defunct(struct_hash)
        raw_sig = Account.sign_message(msg, self.private_key).signature
        if isinstance(raw_sig, bytes):
            signature = "0x" + raw_sig.hex()
        else:
            signature = raw_sig if raw_sig.startswith("0x") else "0x" + raw_sig

        # 5. Submit to relayer
        payload = {
            "type": "PROXY",
            "from": eoa,
            "to": to_field,
            "proxyWallet": proxy_addr,
            "data": encoded_data,
            "nonce": str(nonce),
            "signature": signature,
            "signatureParams": {
                "gasPrice": gas_price,
                "gasLimit": gas_limit,
                "relayerFee": relayer_fee,
                "relayHub": RELAY_HUB,
                "relay": relay_address,
            },
        }

        headers = {
            "RELAYER_API_KEY": relayer_api_key,
            "RELAYER_API_KEY_ADDRESS": os.getenv("RELAYER_API_KEY_ADDRESS"),
            "Content-Type": "application/json",
        }

        print(f"📤 Submitting to relayer...")
        resp = requests.post(f"{RELAYER_URL}/submit", json=payload, headers=headers)

        if resp.status_code != 200:
            raise Exception(f"Relayer error {resp.status_code}: {resp.text}")

        result = resp.json()
        tx_id = result.get("transactionID")
        print(f"📋 Relayer tx ID: {tx_id}, state: {result.get('state')}")

        # 6. Poll for confirmation
        for i in range(30):
            time.sleep(3)
            check = requests.get(f"{RELAYER_URL}/transaction", params={"id": tx_id}).json()
            if isinstance(check, list) and check:
                check = check[0]
            state = check.get("state", "")
            tx_hash = check.get("transactionHash", "")
            print(f"   ⏳ Poll {i+1}: {state} {tx_hash[:20] if tx_hash else ''}")

            if state in ("STATE_CONFIRMED", "STATE_MINED"):
                print(f"✅ Relayer tx confirmed: {tx_hash}")
                return tx_hash
            if state in ("STATE_FAILED", "STATE_INVALID"):
                raise Exception(f"Relayer tx failed: {state} - {tx_hash}")

        raise Exception(f"Relayer tx {tx_id} timed out after 90s")

    def _ensure_adapter_approval(self):
        """Checks if NegRisk Adapter is approved on CTF. Approves via relayer if not."""
        w3 = self._get_web3()
        proxy_addr = Web3.to_checksum_address(self.proxy_address)
        ctf = w3.eth.contract(
            address=Web3.to_checksum_address(CTF_ADDRESS),
            abi=CTF_ABI
        )
        adapter_addr = Web3.to_checksum_address(NEG_RISK_ADAPTER_ADDRESS)

        is_approved = ctf.functions.isApprovedForAll(proxy_addr, adapter_addr).call()
        if is_approved:
            print("✅ NegRisk Adapter already approved on CTF.")
            return

        print("🔐 Approving NegRisk Adapter on CTF contract (via relayer)...")
        raw_cd = ctf.functions.setApprovalForAll(adapter_addr, True)._encode_transaction_data()
        calldata_hex = raw_cd if isinstance(raw_cd, str) and raw_cd.startswith("0x") else "0x" + (raw_cd.hex() if isinstance(raw_cd, bytes) else raw_cd)
        self._exec_via_relayer(CTF_ADDRESS, calldata_hex)

    def _resolve_onchain_question_index(self, neg_risk_market_id, condition_id, max_questions=30):
        """
        Finds the on-chain question index by matching the conditionId.
        On-chain: conditionId = keccak256(adapter_address + questionId + outcomeSlotCount)
        where questionId = marketId + index (simple addition, NOT a hash).
        The API array order does NOT match the on-chain question index!
        """
        from eth_utils import keccak as eth_keccak

        adapter_bytes = bytes.fromhex(NEG_RISK_ADAPTER_ADDRESS[2:].lower())
        market_id_int = int(neg_risk_market_id, 16)
        target_cid = condition_id.lower().replace("0x", "")

        for i in range(max_questions):
            question_id_bytes = (market_id_int + i).to_bytes(32, "big")
            packed = adapter_bytes + question_id_bytes + (2).to_bytes(32, "big")
            computed_cid = eth_keccak(packed).hex()

            if computed_cid == target_cid:
                print(f"✅ On-chain question index resolved: {i} (API conditionId matched)")
                return i

        raise Exception(f"Could not resolve on-chain question index for conditionId {condition_id}")

    def _convert_positions_onchain(self, neg_risk_market_id, condition_id, amount):
        """
        Calls convertPositions on the NegRisk Adapter via the Relayer API.
        The relayer executes through the proxy wallet (gasless, no owner key needed).
        Resolves the correct on-chain question index from the conditionId.
        """
        # Ensure the adapter is approved to move proxy's CTF tokens
        self._ensure_adapter_approval()

        # Resolve the REAL on-chain question index (API array order != on-chain order)
        market_index = self._resolve_onchain_question_index(neg_risk_market_id, condition_id)

        w3 = Web3()
        adapter = w3.eth.contract(
            address=Web3.to_checksum_address(NEG_RISK_ADAPTER_ADDRESS),
            abi=NEG_RISK_ADAPTER_ABI
        )

        index_set = 1 << market_index
        market_id_bytes = Web3.to_bytes(hexstr=neg_risk_market_id)
        raw_amount = int(amount * 1_000_000)

        print(f"📝 convertPositions(marketId={neg_risk_market_id}, indexSet={index_set}, amount={raw_amount})")

        raw_cd = adapter.functions.convertPositions(
            market_id_bytes,
            index_set,
            raw_amount
        )._encode_transaction_data()
        calldata_hex = raw_cd if isinstance(raw_cd, str) and raw_cd.startswith("0x") else "0x" + (raw_cd.hex() if isinstance(raw_cd, bytes) else raw_cd)

        self._exec_via_relayer(NEG_RISK_ADAPTER_ADDRESS, calldata_hex)

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