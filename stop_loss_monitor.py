import asyncio
import json
import sys
import threading
from datetime import datetime
import websockets
from websockets.exceptions import ConnectionClosed, ConnectionClosedError, ConnectionClosedOK
from order_executor import OrderExecutor
from config_manager import config
from notification_manager import Notifier
from shared_queue import get_parsed_command, command_queue
from get_positions import fetch_polymarket_positions
from filter_by_90_114 import GetMarkets
import os
from x_stream_monitor import XStreamManager

sys.stdout.reconfigure(line_buffering=True)

# --- STOP LOSS CONFIG ---
stop_loss_cache = config.get_stop_loss_threshold()

# --- ORDER PLACER CONFIG ---
order_config = {
    "side": "BUY",
    "size": 2,
    "price": 0.99,
    "market": "40-64",
    "seriesSlug": "elon-tweets-48h"
}
order_state = "RUNNING"

# --- TWILIO CALL TOGGLE ---
call_enabled = False

# --- WEBSOCKET CONFIG ---
WS_URI = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
RECONNECT_DELAY = 5
MAX_RECONNECT_DELAY = 60

# --- SHARED STATE ---
price_update_queue = asyncio.Queue()
subscribe_event = asyncio.Event()


async def handle_telegram_commands(executor):
    """
    Polls the Telegram command queue every 0.5s.
    Handles ALL commands: stop-loss management + order placer control.
    """
    global stop_loss_cache, order_state

    while True:
        await asyncio.sleep(0.5)

        message = get_parsed_command()
        new_command = message[0].lower() if message else None

        if not new_command:
            continue

        print(f"📥 Command received: {new_command}")

        try:
            # --- STOP LOSS COMMANDS ---
            if new_command == '/global_threshold' and len(message) > 1:
                new_threshold = float(message[1])
                await asyncio.to_thread(config.update_stop_loss_threshold, new_threshold)
                stop_loss_cache = new_threshold
                await asyncio.to_thread(Notifier._send, f"✅ Global stop loss threshold updated to ${new_threshold}")
                print(f"✅ RAM CACHE UPDATED TO: {stop_loss_cache}")

            elif new_command == "/token_stop_loss" and len(message) > 2:
                await asyncio.to_thread(config.modify_token_stop_loss, message[1], message[2])
                await asyncio.to_thread(Notifier._send, f"✅ Stop loss for token {message[1]} updated to {message[2]}")

            elif new_command == "/list_token_ids":
                await asyncio.to_thread(Notifier.list_token_ids)

            elif new_command == "/update_token_ids":
                await asyncio.to_thread(fetch_polymarket_positions)
                subscribe_event.set()

            elif new_command == "/r_i_t":
                await asyncio.to_thread(config.remove_inactive_tokens)
                await asyncio.to_thread(Notifier._send, "✅ Inactive tokens removed from monitoring.")

            elif new_command == "/r_b_t_i" and len(message) > 1:
                await asyncio.to_thread(config.remove_by_token_id, message[1])
                await asyncio.to_thread(Notifier._send, "✅ Token removed from monitoring.")

            elif new_command == "/t_t_m" and len(message) > 1:
                token_status = await asyncio.to_thread(config.toggle_token_monitoring, message[1], "is_active")
                await asyncio.to_thread(Notifier._send, token_status)

            elif new_command == "/t_o_l" and len(message) > 1:
                token_status = await asyncio.to_thread(config.toggle_token_monitoring, message[1], "is_one_left")
                await asyncio.to_thread(Notifier._send, token_status)

            # --- ORDER PLACER COMMANDS ---
            elif new_command == "/stop":
                order_state = "STOPPED"
                await asyncio.to_thread(Notifier._send, "⏸ Order placer paused.")
                print("🛑 Order placer paused.")

            elif new_command == "/start":
                order_state = "RUNNING"
                await asyncio.to_thread(Notifier._send, "▶️ Order placer resumed.")
                print("✅ Order placer resumed.")

            elif new_command == "/set_slug" and len(message) > 1:
                slug_option = message[1].lower()
                if slug_option in ("48h", "1"):
                    order_config["seriesSlug"] = "elon-tweets-48h"
                elif slug_option in ("normal", "2"):
                    order_config["seriesSlug"] = "elon-tweets"
                else:
                    await asyncio.to_thread(Notifier._send, "❌ Invalid option. Use: /set\\_slug 48h or /set\\_slug normal")
                    continue
                await asyncio.to_thread(Notifier._send, f"✅ seriesSlug updated to: {order_config['seriesSlug']}")

            elif new_command == "/set_date" and len(message) > 1:
                new_date = message[1]
                try:
                    datetime.fromisoformat(new_date.replace("Z", "+00:00"))
                    await asyncio.to_thread(config.update_last_processed_date, new_date)
                    await asyncio.to_thread(Notifier._send, f"✅ LAST\\_EVENT\\_CREATED\\_DATE updated to: {new_date}")
                except ValueError:
                    await asyncio.to_thread(Notifier._send, "❌ Invalid date format. Use: /set\\_date 2026-03-23T16:00:01.618210Z")

            elif new_command == "/set_next_buy" and len(message) > 1:
                buy_bracket = message[1]
                series_slug = order_config["seriesSlug"]
                try:
                    bracket_data = await asyncio.to_thread(GetMarkets.get_active_bracket, buy_bracket, series_slug)
                    if bracket_data:
                        yes_token_id = bracket_data["yes_token_id"]
                        market_title = bracket_data["market"]
                        data = {
                            "stop_loss": 0,
                            "size": float(order_config["size"]),
                            "actual_price": 0,
                            "is_active": False,
                            "bracket": market_title,
                            "is_one_left": False,
                            "is_buy_next": True
                        }
                        await asyncio.to_thread(config.update_nested, "TOKEN_IDs", yes_token_id, data)
                        await asyncio.to_thread(Notifier._send, f"✅ Next buy set: {market_title}\nToken: ...{yes_token_id[-5:]}")
                    else:
                        await asyncio.to_thread(Notifier._send, "❌ Could not find active market for that bracket.")
                except Exception as e:
                    await asyncio.to_thread(Notifier._send, f"❌ Error setting next buy: {e}")

            elif new_command == "/t_b" and len(message) > 1:
                token_status = await asyncio.to_thread(config.toggle_token_monitoring, message[1], "is_buy_next")
                await asyncio.to_thread(Notifier._send, token_status)

            elif new_command == "/buy_no":
                bracket_key = message[1] if len(message) > 1 else order_config["market"]
                series_slug = order_config["seriesSlug"]
                size = float(message[2]) if len(message) > 2 else order_config["size"]
                price = float(message[3]) if len(message) > 3 else order_config["price"]
                try:
                    await asyncio.to_thread(Notifier._send, f"🔍 Fetching market data for {bracket_key}...")
                    market_data = await asyncio.to_thread(GetMarkets.get_active_market, bracket_key, series_slug)
                    if market_data:
                        no_token_id = market_data["no_token_id"]
                        neg_risk_market_id = market_data["neg_risk_market_id"]
                        condition_id = market_data["condition_id"]
                        market_title = market_data["market"]
                        await asyncio.to_thread(Notifier._send, f"🎯 Buying {size} NO @ ${price} on {market_title[:30]}...")
                        order_id = await asyncio.to_thread(
                            executor.buy_and_convert, no_token_id, neg_risk_market_id, condition_id, price, size
                        )
                        if order_id:
                            await asyncio.to_thread(Notifier.notify_trade, market_title, "BUY+CONVERT", size, price, order_id)
                        else:
                            await asyncio.to_thread(Notifier._send, "❌ Buy+Convert failed. Check logs.")
                    else:
                        await asyncio.to_thread(Notifier._send, f"❌ No active market found for bracket '{bracket_key}'.")
                except Exception as e:
                    await asyncio.to_thread(Notifier._send, f"❌ Error: {e}")

            elif new_command == "/t_call":
                global call_enabled
                call_enabled = not call_enabled
                status = "ON 🔔" if call_enabled else "OFF 🔕"
                await asyncio.to_thread(Notifier._send, f"📞 Twilio calls: {status}")

            elif new_command == "/help":
                help_text = (
                    "*Stop Loss*\n"
                    "/global\\_threshold `<value>` — Set global SL threshold\n"
                    "/token\\_stop\\_loss `<id>` `<value>` — Set SL for a token\n"
                    "/list\\_token\\_ids — List all monitored tokens\n"
                    "/update\\_token\\_ids — Sync tokens from Polymarket\n"
                    "/r\\_i\\_t — Remove inactive tokens\n"
                    "/r\\_b\\_t\\_i `<suffix>` — Remove token by ID suffix\n"
                    "/t\\_t\\_m `<suffix>` — Toggle is\\_active\n"
                    "/t\\_o\\_l `<suffix>` — Toggle is\\_one\\_left\n"
                    "/t\\_b `<suffix>` — Toggle is\\_buy\\_next\n\n"
                    "*Order Placer*\n"
                    "/set `<side>` `<size>` `<price>` `<market>` — Config order\n"
                    "/set\\_slug `<48h|normal>` — Set series slug\n"
                    "/set\\_date `<ISO date>` — Set last processed date\n"
                    "/set\\_next\\_buy `<bracket>` — Pre-cache bracket for tweet buy\n"
                    "/buy\\_no `[bracket]` `[size]` `[price]` — Buy NO + convert now\n"
                    "/stop — Pause order placer\n"
                    "/start — Resume order placer\n"
                    "/t\\_call — Toggle Twilio phone calls (default: OFF)"
                )
                await asyncio.to_thread(Notifier._send, help_text)

            elif new_command == "/set" and len(message) == 5:
                try:
                    new_side = message[1].upper()
                    new_size = float(message[2].replace(',', '.'))
                    new_price = float(message[3].replace(',', '.'))
                    new_market = message[4]

                    order_config["side"] = new_side
                    order_config["size"] = new_size
                    order_config["price"] = new_price
                    order_config["market"] = new_market

                    msg = f"✅ Order config updated:\nSide: {new_side}\nSize: {new_size}\nPrice: {new_price}\nMarket: {new_market}"
                    print(msg)
                    await asyncio.to_thread(Notifier._send, msg)
                except ValueError:
                    await asyncio.to_thread(Notifier.notify_error, "❌ Invalid numbers. Use: /set BUY 21 0.05 65-89")

        except Exception as e:
            print(f"❌ Error processing command '{new_command}': {e}")
            await asyncio.to_thread(Notifier._send, f"❌ Error processing command: {e}")


async def process_price_updates(executor):
    """
    Consumes price updates from the queue and applies stop loss logic.
    Runs independently — never touches the WebSocket directly.
    """
    global stop_loss_cache

    while True:
        try:
            token_id, current_price, TOKENS = await price_update_queue.get()

            if token_id not in TOKENS:
                continue

            size = TOKENS[token_id]["size"]
            limit = TOKENS[token_id]["stop_loss"]
            actual_price = TOKENS[token_id]["actual_price"]
            new_stop_loss = round(current_price - stop_loss_cache, 2)
            bracket = (TOKENS[token_id].get("bracket") or "")[20:]

            if current_price > actual_price:
                await asyncio.to_thread(config.modify_token_stop_loss, token_id[-5:], new_stop_loss, current_price)
                print(f"📈 PRICE STILL HIGH: {token_id[:10]}... -> ${current_price}")
                TOKENS[token_id]["actual_price"] = current_price
                TOKENS[token_id]["stop_loss"] = new_stop_loss

            elif current_price <= limit and TOKENS[token_id]["is_active"]:
                print(f"\n🚨 SELLING {token_id} at ${current_price}")
                await asyncio.to_thread(Notifier._send, f"\nSOLD {bracket} at ${current_price} due to stop loss trigger.")
                await asyncio.to_thread(executor.sell_rapidly, token_id, size)
                await asyncio.to_thread(config.toggle_token_monitoring, token_id[-5:], "is_active")

        except Exception as e:
            print(f"❌ Error processing price update: {e}")


async def run_websocket_monitor(executor):
    """
    Purely responsible for: connecting, subscribing, and receiving messages.
    Puts price updates into price_update_queue — does NOT do business logic.
    """
    reconnect_delay = RECONNECT_DELAY

    while True:
        try:
            async with websockets.connect(
                WS_URI,
                ping_interval=30,
                ping_timeout=20,
                close_timeout=10,
                additional_headers={
                    "User-Agent": "Mozilla/5.0 (compatible; PolymarketBot/1.0)"
                }
            ) as websocket:

                print(f"✅ Connected!")
                reconnect_delay = RECONNECT_DELAY
                consecutive_timeouts = 0
                subscribed_tokens = set()

                while True:
                    TOKENS = config.get("TOKEN_IDs", {})
                    current_token_ids = set(TOKENS.keys())
                    new_tokens = current_token_ids - subscribed_tokens

                    if new_tokens or subscribe_event.is_set():
                        subscribe_event.clear()
                        if new_tokens:
                            print(f"🔄 Subscribing to {len(new_tokens)} new tokens...")
                            await websocket.send(json.dumps({
                                "type": "subscribe",
                                "assets_ids": list(new_tokens),
                                "channels": ["book"]
                            }))
                            subscribed_tokens.update(new_tokens)

                    try:
                        msg = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                        consecutive_timeouts = 0
                    except asyncio.TimeoutError:
                        consecutive_timeouts += 1
                        if consecutive_timeouts >= 45:
                            break
                        continue

                    try:
                        raw_data = json.loads(msg)
                    except json.JSONDecodeError:
                        continue

                    updates = [raw_data] if isinstance(raw_data, dict) else raw_data if isinstance(raw_data, list) else []

                    for update in updates:
                        if not isinstance(update, dict):
                            continue

                        bids = update.get("bids", [])
                        token_id = update.get("asset_id")

                        if not token_id or not bids:
                            continue

                        best_bid = bids[-1]
                        current_price = 0.0

                        if isinstance(best_bid, dict):
                            current_price = float(best_bid.get("price", 0))
                        elif isinstance(best_bid, list):
                            try:
                                current_price = float(best_bid[0])
                            except (IndexError, ValueError):
                                continue
                        else:
                            continue

                        print(f"📉 {token_id[:10]}... -> ${current_price}")
                        await price_update_queue.put((token_id, current_price, TOKENS))

        except (ConnectionClosed, ConnectionClosedError, ConnectionClosedOK, OSError) as e:
            print(f"\n⚠️ WebSocket closed: {e}")
        except Exception as e:
            print(f"\n❌ Critical WebSocket error: {e}")

        await asyncio.sleep(reconnect_delay)
        reconnect_delay = min(reconnect_delay * 2, MAX_RECONNECT_DELAY)


async def emergency_tweet_sell(executor):
    print("⚡ X API TRIGGER: INITIATING EMERGENCY SELL PROTOCOL ⚡")
    TOKENS = config.get("TOKEN_IDs", {})

    if not TOKENS:
        print("📭 No tokens to sell.")
        return

    for token_id, token_data in TOKENS.items():
        if token_data.get("is_one_left"):
            size = token_data.get("size", 0.0)
            bracket = (token_data.get("bracket") or "Unknown")[20:]
            if size > 0:
                print(f"🚨 LIQUIDATING {token_id} DUE TO ELON TWEET!")
                await asyncio.to_thread(executor.sell_rapidly, token_id, size)
                await asyncio.to_thread(Notifier._send, f"\nSOLD {bracket} instantly due to a new tweet detected.")
                await asyncio.to_thread(config.toggle_token_monitoring, token_id[-5:], "is_one_left")

    print("✅ Emergency sell protocol complete.")


async def emergency_tweet_buy(executor):
    print("⚡ X API TRIGGER: INITIATING TWEET BUY PROTOCOL ⚡")
    TOKENS = config.get("TOKEN_IDs", {})

    if not TOKENS:
        print("📭 No tokens configured for tweet buy.")
        return

    for token_id, token_data in TOKENS.items():
        if token_data.get("is_buy_next"):
            size = order_config["size"]
            price = order_config["price"]
            bracket = (token_data.get("bracket") or "Unknown")[20:]
            try:
                print(f"🚨 BUYING YES on {bracket} DUE TO ELON TWEET!")
                order_id = await asyncio.to_thread(executor.buy_yes_direct, token_id, price, size)
                if order_id:
                    await asyncio.to_thread(Notifier._send, f"🎯 BOUGHT YES on {bracket} instantly due to tweet! Order: {order_id}")
                else:
                    await asyncio.to_thread(Notifier._send, f"❌ Failed to buy YES on {bracket}")
                await asyncio.to_thread(config.toggle_token_monitoring, token_id[-5:], "is_buy_next")
            except Exception as e:
                print(f"❌ Tweet buy error: {e}")
                await asyncio.to_thread(Notifier._send, f"❌ Tweet buy error: {e}")

    print("✅ Tweet buy protocol complete.")


async def scan_and_place_orders(executor):
    """
    Scans for new Elon tweet-count markets and places limit orders.
    Runs every 2s when order_state is RUNNING. All blocking I/O is offloaded.
    """
    SCAN_INTERVAL = 2

    while True:
        if order_state == "RUNNING":
            try:
                market_key = order_config["market"]
                series_slug = order_config["seriesSlug"]

                markets = await asyncio.to_thread(GetMarkets.get_market, market_key, series_slug)

                if markets and markets.get("isNewMarket"):
                    no_token_id = markets["clob_ids"][1]  # NO token
                    neg_risk_market_id = markets["neg_risk_market_id"]
                    condition_id = markets["api_condition_id"]
                    size = order_config["size"]
                    price = order_config["price"]
                    market_title = markets["market"]

                    print(f"🎯 New market found! Buying {size} No @ ${price} + converting")

                    try:
                        order_id = await asyncio.to_thread(
                            executor.buy_and_convert, no_token_id, neg_risk_market_id, condition_id, price, size
                        )
                        if order_id:
                            await asyncio.to_thread(
                                Notifier.notify_trade, market_title, "BUY+CONVERT", size, price, order_id
                            )
                    except Exception as e:
                        print(f"❌ Order placement error: {e}")
                        await asyncio.to_thread(Notifier.notify_error, f"Failed placing order: {e}")

            except Exception as e:
                print(f"❌ Market scan error: {e}")

        await asyncio.sleep(SCAN_INTERVAL)


async def main():
    executor = OrderExecutor

    if not hasattr(executor, 'client') or not executor.client:
        print("❌ Warning: OrderExecutor client may not be fully initialized.")

    # Start Telegram polling in a background thread (blocking long-poll)
    telegram_thread = threading.Thread(
        target=Notifier.check_for_commands,
        args=(command_queue,),
        daemon=True
    )
    telegram_thread.start()
    print("✅ Telegram listener started.")

    x_token = os.getenv("X_BEARER_TOKEN")
    if not x_token:
        print("❌ CRITICAL: X_BEARER_TOKEN not found in environment variables.")
        return

    async def sell_trigger():
        await emergency_tweet_sell(executor)

    async def buy_trigger():
        await emergency_tweet_buy(executor)

    x_monitor = XStreamManager(bearer_token=x_token, sell_trigger=sell_trigger, buy_trigger=buy_trigger, call_check=lambda: call_enabled)

    print("✅ System Core Online — all 5 tasks launching.")

    await asyncio.gather(
        run_websocket_monitor(executor),          # 1. Price stream via WebSocket
        handle_telegram_commands(executor),        # 2. Telegram command handler
        process_price_updates(executor),           # 3. Stop-loss logic
        x_monitor.start_listening(),               # 4. X/Twitter stream
        scan_and_place_orders(executor),           # 5. Market scanner + order placer
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped.")
