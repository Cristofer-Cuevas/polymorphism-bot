import asyncio
import time
import json
import websockets
from order_placer import OrderExecutor # Import your existing class
from config_manager import config

# --- CONFIGURATION ---
TARGET_TOKEN_ID = "YOUR_LONG_TOKEN_ID_HERE"
STOP_LOSS_PRICE = 0.30
SELL_AMOUNT = 50.0

# 1. THE WEBSOCKET TASK (Async)
# We pass the 'existing_client' as an argument so we don't create a new one.
async def run_websocket_monitor(executor):

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
            async with websockets.connect(uri) as websocket:
                print(f"👀 Vigilando {len(TOKEN_IDs)} mercados a la vez...")

                # 1. Suscripción MASIVA (Una sola petición)
                # await websocket.send(json.dumps({
                #     "type": "subscribe",
                #     "assets_ids": TOKEN_IDs, # <--- ¡Aquí va la lista!
                #     "channels": ["book"]
                # }))

                subscribed_tokens = set()

                while True:

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
                            print(f"📉 {token_id[:10]}... -> ${current_price}", end="\r")

                            # Buscamos en config si este token está vigilado
                            # (Asumiendo que tienes cargada tu config)
                            if token_id in TOKENS:
                                size = TOKENS[token_id]["size"]
                                # print("size", size)
                                limit = TOKENS[token_id]["stop_loss"]
                                actual_price = TOKENS[token_id]["actual_price"]
                                new_stop_loss = round(current_price - 0.05, 2)
                                if current_price <= limit:
                                    print(f"\n🚨 VENDIENDO {token_id} a ${current_price}")
                                        
                                        # Run the blocking HTTP request in a background thread
                                    await asyncio.to_thread(executor.sell_rapidly, token_id, size)
                                        
                                        # Run the blocking database write in a background thread
                                    await asyncio.to_thread(config.remove_monitored_token, token_id)
                                elif current_price > actual_price:
                                    await asyncio.to_thread(config.modify_token_stop_loss, token_id, new_stop_loss, current_price)
                                    print("PRICE ISTILL HIGH AF")
                                    TOKENS[token_id]["actual_price"] = current_price
                                    TOKENS[token_id]["stop_loss"] = new_stop_loss

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
    # A. Initialize your SINGLE connection
    executor = OrderExecutor
    
    # Check if connected
    if not executor.client:
        print("❌ Failed to connect OrderExecutor.")
        return

    print("✅ Shared Connection Established.")

    # B. Run both tasks in parallel
    # gather() runs them at the same time. If one waits, the other runs.
    await asyncio.gather(
        run_websocket_monitor(executor),
        # run_existing_bot_loop(executor)
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped.")