"""
Test script to verify Polymarket Relayer API signing works.
Uses a safe, idempotent operation: setApprovalForAll (already approved = no-op on-chain).
"""
import os
import time
import requests
from dotenv import load_dotenv
from web3 import Web3
from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import keccak

load_dotenv()

# --- Config ---
RELAYER_URL = "https://relayer-v2.polymarket.com"
PROXY_FACTORY = "0xaB45c5A4B0c941a2F231C04C3f49182e1A254052"
RELAY_HUB = "0xD216153c06E857cD7f72665E0aF1d7D82172F494"
CTF_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
NEG_RISK_ADAPTER = "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296"

PRIVATE_KEY = os.getenv("PRIVATE_KEY")
PROXY_ADDRESS = os.getenv("PROXY_ADDRESS")

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
        "name": "setApprovalForAll",
        "inputs": [
            {"name": "_operator", "type": "address"},
            {"name": "_approved", "type": "bool"}
        ],
        "outputs": [],
        "stateMutability": "nonpayable"
    },
    {
        "type": "function",
        "name": "isApprovedForAll",
        "inputs": [
            {"name": "_owner", "type": "address"},
            {"name": "_operator", "type": "address"}
        ],
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view"
    }
]


def test_relayer():
    eoa = Account.from_key(PRIVATE_KEY).address
    proxy_addr = Web3.to_checksum_address(PROXY_ADDRESS)

    print(f"EOA: {eoa}")
    print(f"Proxy: {proxy_addr}")
    print()

    # --- Step 0: Verify approval status (read-only) ---
    print("=" * 60)
    print("STEP 0: Check current approval status (read-only)")
    print("=" * 60)
    from web3.middleware import ExtraDataToPOAMiddleware
    w3_live = Web3(Web3.HTTPProvider(os.getenv("POLYGON_RPC_URL", "https://polygon-rpc.com")))
    w3_live.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    ctf_live = w3_live.eth.contract(address=Web3.to_checksum_address(CTF_ADDRESS), abi=CTF_ABI)
    approved = ctf_live.functions.isApprovedForAll(proxy_addr, Web3.to_checksum_address(NEG_RISK_ADAPTER)).call()
    print(f"  isApprovedForAll(proxy, adapter) = {approved}")
    print(f"  (This means our test tx is a safe no-op)")
    print()

    # --- Step 1: Get relay payload ---
    print("=" * 60)
    print("STEP 1: Get relay payload from /relay-payload")
    print("=" * 60)
    rp_resp = requests.get(
        f"{RELAYER_URL}/relay-payload",
        params={"address": eoa, "type": "PROXY"}
    )
    print(f"  Status: {rp_resp.status_code}")
    print(f"  Response: {rp_resp.text}")

    if rp_resp.status_code != 200:
        print("FAILED: Cannot reach relay-payload endpoint")
        return

    rp = rp_resp.json()
    relay_address = rp["address"]
    nonce = rp["nonce"]
    print(f"  Relay address: {relay_address}")
    print(f"  Nonce: {nonce}")
    print()

    # --- Step 2: Encode calldata ---
    print("=" * 60)
    print("STEP 2: Encode setApprovalForAll calldata wrapped in proxy()")
    print("=" * 60)
    w3 = Web3()
    ctf = w3.eth.contract(address=Web3.to_checksum_address(CTF_ADDRESS), abi=CTF_ABI)
    raw_inner = ctf.functions.setApprovalForAll(
        Web3.to_checksum_address(NEG_RISK_ADAPTER), True
    )._encode_transaction_data()
    # _encode_transaction_data() returns str in newer web3, bytes in older
    if isinstance(raw_inner, str):
        inner_calldata_hex = raw_inner if raw_inner.startswith("0x") else "0x" + raw_inner
        inner_calldata_bytes = bytes.fromhex(inner_calldata_hex[2:])
    else:
        inner_calldata_hex = "0x" + raw_inner.hex()
        inner_calldata_bytes = raw_inner
    print(f"  Inner calldata (setApprovalForAll): {inner_calldata_hex}")

    proxy_contract = w3.eth.contract(address=proxy_addr, abi=PROXY_ABI)
    calls = [(1, Web3.to_checksum_address(CTF_ADDRESS), 0, inner_calldata_bytes)]
    raw_outer = proxy_contract.functions.proxy(calls)._encode_transaction_data()
    encoded_data = raw_outer if isinstance(raw_outer, str) and raw_outer.startswith("0x") else "0x" + (raw_outer.hex() if isinstance(raw_outer, bytes) else raw_outer)
    print(f"  Outer calldata (proxy): {encoded_data[:80]}...")
    print(f"  Calldata length: {len(encoded_data)} chars")
    print()

    # --- Step 3: Build struct hash ---
    print("=" * 60)
    print("STEP 3: Build struct hash")
    print("=" * 60)
    gas_limit = "100000"
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
    print(f"  Struct hash: 0x{struct_hash.hex()}")
    print(f"  Data to hash length: {len(data_to_hash)} bytes")
    print()

    # --- Step 4: Sign ---
    print("=" * 60)
    print("STEP 4: EIP-191 personal sign")
    print("=" * 60)
    msg = encode_defunct(struct_hash)
    raw_sig = Account.sign_message(msg, PRIVATE_KEY).signature
    if isinstance(raw_sig, bytes):
        signature = "0x" + raw_sig.hex()
    else:
        signature = raw_sig if raw_sig.startswith("0x") else "0x" + raw_sig
    print(f"  Signature: {signature[:40]}...")
    print(f"  Signature length: {len(signature)} chars (should be 132)")
    print()

    # --- Step 5: Submit ---
    print("=" * 60)
    print("STEP 5: Submit to relayer")
    print("=" * 60)
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
        "RELAYER_API_KEY": "019d221f-ffaf-75bb-9ecb-f015cad71235",
        "RELAYER_API_KEY_ADDRESS": "0x25b751b1e8651b592ea120e16c2fc974469d3e24",
        "Content-Type": "application/json",
    }

    print(f"  Payload keys: {list(payload.keys())}")
    print(f"  from: {payload['from']}")
    print(f"  to: {payload['to']}")
    print(f"  proxyWallet: {payload['proxyWallet']}")
    print(f"  nonce: {payload['nonce']}")
    print()

    resp = requests.post(f"{RELAYER_URL}/submit", json=payload, headers=headers)
    print(f"  Status: {resp.status_code}")
    print(f"  Response: {resp.text}")

    if resp.status_code != 200:
        print(f"\n  FAILED at submission. Error: {resp.text}")
        print("\n  Possible issues:")
        print("    - Signature mismatch (struct hash encoding wrong)")
        print("    - Wrong 'to' field (should it be proxy_addr instead of PROXY_FACTORY?)")
        print("    - Invalid RELAYER_API_KEY")
        print("    - Missing/wrong fields in payload")
        return

    result = resp.json()
    tx_id = result.get("transactionID")
    print(f"\n  TX ID: {tx_id}")
    print(f"  State: {result.get('state')}")
    print()

    # --- Step 6: Poll ---
    print("=" * 60)
    print("STEP 6: Poll for confirmation")
    print("=" * 60)
    for i in range(20):
        time.sleep(3)
        check = requests.get(f"{RELAYER_URL}/transaction", params={"id": tx_id}).json()
        if isinstance(check, list) and check:
            check = check[0]
        state = check.get("state", "")
        tx_hash = check.get("transactionHash", "")
        print(f"  Poll {i+1}: state={state} tx={tx_hash[:30] if tx_hash else 'pending'}")

        if state in ("STATE_CONFIRMED", "STATE_MINED"):
            print(f"\n  SUCCESS! TX confirmed: {tx_hash}")
            print(f"  View on Polygonscan: https://polygonscan.com/tx/{tx_hash}")
            return
        if state in ("STATE_FAILED", "STATE_INVALID"):
            print(f"\n  FAILED! State: {state}")
            print(f"  Full response: {check}")
            return

    print("\n  TIMEOUT: TX not confirmed after 60s")


if __name__ == "__main__":
    test_relayer()
