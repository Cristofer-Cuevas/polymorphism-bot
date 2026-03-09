import os
import requests
import asyncio
from config_manager import config
from notification_manager import Notifier

# The wallet address used to hold the funds on Polymarket (usually the Proxy Wallet)
# Ensure this variable is explicitly added to the .env file in the AWS server
PROXY_WALLET_ADDRESS = os.getenv("PROXY_ADDRESS", "0x84056697FC969E3711431d5871d6A8490Cd5CBa8")

def fetch_polymarket_positions():
    """
    Fetches real-time portfolio positions directly from the Polymarket Data API.
    Filters out empty or dust positions using the sizeThreshold parameter.
    """
    # The official Polymarket Data API endpoint for querying user portfolios
    url = "https://data-api.polymarket.com/positions"
    
    # Query parameters based on the Polymarket API documentation
    params = {
        "user": PROXY_WALLET_ADDRESS,
        "sizeThreshold": "0.01", # Strictly ignore empty positions
        "sortBy": "TOKENS",
        "sortDirection": "DESC",
        "limit": 50
    }
    
    headers = {
        "Accept": "application/json"
    }
    
    is_token_added = False

    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        print("response", response.json())
        positions = response.json()
        for pos in positions:
            if not config.is_token_monitored(pos.get('asset')):
                config.add_monitored_token(
                    token_id=pos.get('asset'),
                    stop_loss=round(float(pos.get('curPrice', 0.0)) - 0.10, 2),  # Default stop loss, can be updated later
                    size=pos.get('size', 0.0),
                    price=pos.get('curPrice', 0.0),
                    slug=pos.get('slug', '')[20:],
                    is_one_left=False
                )
                is_token_added = True
                
                
        # return response.json()

        if is_token_added:
            Notifier._send(f"✅ Portfolio updated with {len(positions)} positions")
            is_token_added = False
        else:
            Notifier._send(f"✅ No new token to add. Portfolio already up to date with {len(positions)} positions.")
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Error fetching data from the Polymarket Data API: {e}")
        return None