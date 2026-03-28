"""Quick debug script to test proxy() encoding and check nonce state."""
import os
from dotenv import load_dotenv
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

load_dotenv()

rpc_url = os.getenv("POLYGON_RPC_URL", "https://polygon-rpc.com")
w3 = Web3(Web3.HTTPProvider(rpc_url))
w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

private_key = os.getenv("PRIVATE_KEY")
proxy_address = os.getenv("PROXY_ADDRESS")

eoa = w3.eth.account.from_key(private_key).address
print(f"EOA: {eoa}")
print(f"Proxy: {proxy_address}")
print(f"EOA balance: {w3.from_wei(w3.eth.get_balance(eoa), 'ether')} POL")
print(f"Current nonce (latest): {w3.eth.get_transaction_count(eoa, 'latest')}")
print(f"Current nonce (pending): {w3.eth.get_transaction_count(eoa, 'pending')}")

# Test the proxy() function selector
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

proxy = w3.eth.contract(address=Web3.to_checksum_address(proxy_address), abi=PROXY_ABI)

# Encode a dummy call to see the selector
dummy_calls = [(1, Web3.to_checksum_address("0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296"), 0, b'\x00')]
encoded = proxy.functions.proxy(dummy_calls)._encode_transaction_data()
print(f"\nFunction selector: {encoded[:10]}")
print(f"Expected proxy((uint8,address,uint256,bytes)[]) selector")

# Try eth_call to simulate (will fail but shows if encoding is right)
print("\n--- Simulating proxy() call via eth_call ---")
try:
    result = proxy.functions.proxy(dummy_calls).call({"from": eoa})
    print(f"Simulation succeeded: {result}")
except Exception as e:
    print(f"Simulation result: {e}")

# Check pending tx for nonce 6
print(f"\n--- Checking if there are stuck txs ---")
pending_nonce = w3.eth.get_transaction_count(eoa, 'pending')
latest_nonce = w3.eth.get_transaction_count(eoa, 'latest')
if pending_nonce > latest_nonce:
    print(f"⚠️ {pending_nonce - latest_nonce} pending tx(s) stuck (nonces {latest_nonce} to {pending_nonce - 1})")
else:
    print("✅ No stuck transactions")
