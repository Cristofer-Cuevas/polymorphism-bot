import asyncio
import time
import json
import websockets
from order_placer import OrderExecutor # Import your existing class
from config_manager import config
from notification_manager import Notifier
from shared_queue import get_parsed_command
from get_positions import fetch_polymarket_positions
import os
from x_stream_monitor import XStreamManager


# --- CONFIGURATION ---
TARGET_TOKEN_ID = "YOUR_LONG_TOKEN_ID_HERE"
STOP_LOSS_PRICE = 0.30
SELL_AMOUNT = 50.0
stop_loss_cache = config.get_stop_loss_threshold()

# 1. THE WEBSOCKET TASK (Async)
# We pass the 'existing_client' as an argument so we don't create a new one.
async def run_websocket_monitor(executor):

    global stop_loss_cache

    uri = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

    # print(config.get_nested("SET_LAST_EVENT_INFO", "LAST_EVENT_ID"))
    
    # Extraemos solo los IDs para la suscripción
    TOKENS = config.get("TOKEN_IDs", {})
    TOKEN_IDs = list(TOKENS.keys())
    print('UDPATING TOKENS')
    # print(TOKENS)
    # print(TOKEN_IDs)

    while True:
        try:
            async with websockets.connect(uri, ping_interval=15, ping_timeout=10, close_timeout=5) as websocket:
                print(f"👀 Vigilando {len(TOKEN_IDs)} mercados a la vez...")

                # 1. Suscripción MASIVA (Una sola petición)
                # await websocket.send(json.dumps({
                #     "type": "subscribe",
                #     "assets_ids": TOKEN_IDs, # <--- ¡Aquí va la lista!
                #     "channels": ["book"]
                # }))

                subscribed_tokens = set()

                while True:
                    # print("Text:", get_parsed_command())
                    message = get_parsed_command()
                    new_command = message[0].lower() if message else None
                    

                    if new_command == '/global_threshold' and len(message) > 1:
                        print(f"📥 Command intercepted: {new_command}")
                        try:
                            # Parse the command (assuming the command is just the float number for now)
                            new_threshold = float(message[1])
                            
                            # Update the database for permanent persistence across reboots
                            config.update_stop_loss_threshold(new_threshold)
                            
                            # CRITICAL: Update the RAM cache so the bot uses the new value instantly
                            # without needing to read the database again.
                            stop_loss_cache = new_threshold
                            Notifier._send(f"✅ Global stop loss threshold updated to ${new_threshold}")
                            print(f"✅ RAM CACHE UPDATED TO: {stop_loss_cache}")
                        except ValueError:
                            print("❌ Invalid command format. Expected a float number.")
                    elif new_command == "/token_stop_loss":
                        await asyncio.to_thread(config.modify_token_stop_loss, message[1], message[2])
                        Notifier._send(f"✅ Stop loss for token {message[1]} updated to {message[2]}")
                    elif new_command == "/list_token_ids":
                        Notifier.list_token_ids()
                    elif new_command == "/update_token_ids":
                        await asyncio.to_thread(fetch_polymarket_positions)
                    elif new_command == "/r_i_t": # Remove Inactive Tokens
                        config.remove_inactive_tokens()
                        Notifier._send("✅ Inactive tokens removed from monitoring.")
                    elif new_command == "/r_b_t_i": # Remove By Token ID
                        config.remove_by_token_id(message[1])
                        print("Message",message)
                        Notifier._send("✅ Token removed from monitoring.")
                    elif new_command == "/t_t_m": # Toggle Token Monitoring
                        token_status = config.toggle_token_monitoring(message[1], "is_active")
                        Notifier._send(token_status)
                    elif new_command == "/t_o_l":
                        token_status = config.toggle_token_monitoring(message[1], "is_one_left")
                        Notifier._send(token_status)

                    TOKENS = config.get("TOKEN_IDs", {})
                    TOKEN_IDs = list(TOKENS.keys())
                    # print('UDPATING TOKENS')
                    current_token_ids = set(TOKENS.keys())

                    new_tokens_to_subscribe = current_token_ids - subscribed_tokens

                    if new_tokens_to_subscribe:
                        print(f"🔄 Found {len(new_tokens_to_subscribe)} new tokens in DB. Subscribing...")
                        
                        # Send the subscription request to Polymarket for the NEW tokens
                        await websocket.send(json.dumps({
                            "type": "subscribe",
                            "assets_ids": list(new_tokens_to_subscribe),
                            "channels": ["book"]
                        }))
                        
                        # Add them to our tracked list so we don't subscribe again
                        subscribed_tokens.update(new_tokens_to_subscribe)

                    # 3. 📩 WAIT FOR THE NEXT PRICE UPDATE
                    # msg = await websocket.recv()
                    # raw_data = json.loads(msg)
                    

                    try:
                        msg = await websocket.recv()
                        raw_data = json.loads(msg)
                        # print(f"📦 Data culpable: {str(raw_data)[:10000]}...")

                        # 1. Normalizar: Asegurarnos de tener siempre una LISTA de actualizaciones
                        if isinstance(raw_data, dict):
                            updates = [raw_data]
                        elif isinstance(raw_data, list):
                            updates = raw_data
                        else:
                            continue # Ignoramos strings sueltos o nulos

                        for update in updates:
                            # 2. Defensa contra elementos que no son diccionarios (ej: strings de keep-alive)
                            if not isinstance(update, dict):
                                continue

                            # 3. Extraer Bids (Compras)
                            bids = update.get("bids", [])
                            token_id = update.get("asset_id")

                            if not token_id or not bids:
                                continue

                            # 4. Analizar el Primer Bid (El mejor precio)
                            best_bid = bids[-1]
                            current_price = 0.0

                            # --- AQUÍ ESTABA EL ERROR ---
                            # Detectamos si el bid es un Diccionario o una Lista
                            if isinstance(best_bid, dict):
                                # Formato estándar: {"price": "0.50", "size": "10"}
                                current_price = float(best_bid.get("price", 0))
                            elif isinstance(best_bid, list):
                                # Formato compacto: ["0.50", "10"] (Precio es el índice 0)
                                try:
                                    current_price = float(best_bid[0])
                                except (IndexError, ValueError):
                                    continue
                            else:
                                # Formato desconocido
                                continue

                            # --- TU LÓGICA DE STOP LOSS ---
                            print(f"📉 {token_id[:10]}... -> ${current_price}")

                            # Buscamos en config si este token está vigilado
                            # (Asumiendo que tienes cargada tu config)
                            if token_id in TOKENS:
                                size = TOKENS[token_id]["size"]
                                # print("size", size)
                                limit = TOKENS[token_id]["stop_loss"]
                                actual_price = TOKENS[token_id]["actual_price"]
                                new_stop_loss = round(current_price - stop_loss_cache, 2)
                                bracket = TOKENS[token_id].get("bracket")[20:]

                                if current_price > actual_price:
                                    await asyncio.to_thread(config.modify_token_stop_loss, token_id[-5:], new_stop_loss, current_price)
                                    print("PRICE ISTILL HIGH AF")
                                    TOKENS[token_id]["actual_price"] = current_price
                                    TOKENS[token_id]["stop_loss"] = new_stop_loss
                                    # elif TOKENS[token_id]["is_one_left"] == True:
                                    #     print(f"\n🚨 VENDIENDO {token_id} a ${current_price}")
                                        
                                    #     Notifier._send(f"\nSOLD {bracket} at ${current_price} due to a new tweet.")
                                            
                                    #         # Run the blocking HTTP request in a background thread
                                    #     # await asyncio.to_thread(executor.sell_rapidly, token_id, size)
                                            
                                    #         # Run the blocking database write in a background thread
                                    # await asyncio.to_thread(config.toggle_token_monitoring, token_id[-5:], "is_active")
                                elif current_price <= limit and TOKENS[token_id]["is_active"] == True:
                                    print(f"\n🚨 VENDIENDO {token_id} a ${current_price}")
                                    
                                    Notifier._send(f"\nSOLD {bracket} at ${current_price} due to stop loss trigger.")
                                        
                                    # Run the blocking HTTP request in a background thread
                                    await asyncio.to_thread(executor.sell_rapidly, token_id, size)
                                        
                                    # Run the blocking database write in a background thread
                                    await asyncio.to_thread(config.toggle_token_monitoring, token_id[-5:], "is_active")
                                


                    # --- RECONNECTION HANDLING ---
                    except websockets.exceptions.ConnectionClosed as e:
                        print(f"\n⚠️ WebSocket Connection Closed: {e}")
                        print("⏳ Reconnecting in 5 seconds...")
                        await asyncio.sleep(5)
                        
                    except json.JSONDecodeError:
                        continue
                        
                    except Exception as e:
                        print(f"\n❌ Critical/Unexpected Error: {e}")
                        print("⏳ Attempting to recover in 5 seconds...")
                        await asyncio.sleep(5)

        except Exception as e:
            print(f"Error WS: {e}")
            await asyncio.sleep(5)

async def emergency_tweet_sell(executor):
    """
    This function acts as the bridge. It gets called ONLY when XStreamManager 
    detects a tweet. It reads the database and sells all active tokens instantly.
    """
    print("⚡ X API TRIGGER: INITIATING EMERGENCY SELL PROTOCOL ⚡")
    
    TOKENS = config.get("TOKEN_IDs", {})
    if not TOKENS:
        print("📭 No tokens to sell.")
        return

    for token_id, token_data in TOKENS.items():
        if token_data.get("is_one_left"):
            size = token_data.get("size", 0.0)
            bracket = token_data.get("bracket", "Unknown")[20:]
            
            if size > 0:
                print(f"🚨 LIQUIDATING {token_id} DUE TO ELON TWEET!")
                
                # Execute the sell order in a background thread to prevent blocking
                await asyncio.to_thread(executor.sell_rapidly, token_id, size)
                Notifier._send(f"\nSOLD {bracket} instantly due to a new tweet detected.")
                
                # Remove from database immediately to prevent double spending
                await asyncio.to_thread(config.toggle_token_monitoring, token_id[-5:], "is_one_left")
                
    print("✅ Emergency sell protocol complete.")

# 2. YOUR OLD BOT LOGIC (Wrapped)
# This wrapper allows your blocking 'while True' loop to run without stopping the WebSocket
async def run_existing_bot_loop(executor):
    print("🤖 Standard Bot: Starting polling loop...")
    
    # We run the blocking loop in a separate thread so it doesn't freeze the WebSocket
    await asyncio.to_thread(executor.start_cycle) 
    # Note: I assume your OrderExecutor has a method like 'start_cycle' 
    # that contains your original 'while True' logic.

# 3. MAIN EXECUTION
async def main():
    executor = OrderExecutor
    
    if not hasattr(executor, 'client') or not executor.client:
        print("❌ Warning: OrderExecutor client may not be fully initialized.")

    print("✅ System Core Online.")

    x_token = os.getenv("X_BEARER_TOKEN")
    if not x_token:
        print("❌ CRITICAL: X_BEARER_TOKEN not found in environment variables.")
        return

    # Use a lambda to pass the executor argument to the emergency function
    trigger_action = lambda: emergency_tweet_sell(executor)
    
    # Initialize the X stream with the specific sell function, NOT the websocket loop
    x_monitor = XStreamManager(bearer_token=x_token, trigger_function=trigger_action)

    # Launch both infinite loops concurrently
    await asyncio.gather(
        run_websocket_monitor(executor),
        x_monitor.start_listening()
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped.")