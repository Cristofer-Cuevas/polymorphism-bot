print("⚡ SYSTEM START: Python is reading the file...")

import os
import sys
import time
from order_executor import OrderExecutor
from filter_by_90_114 import GetMarkets
from notification_manager import Notifier
import threading
import queue
from shared_queue import command_queue
sys.stdout.reconfigure(line_buffering=True)

# Load environment variables from .env file
# load_dotenv()

# command_queue = queue.Queue()

current_config = {
    "side": "BUY",
    "size": 250,      # Cantidad de acciones
    "price": 0.21,  # Precio límite
    "market": "65-89",
    "seriesSlug": "elon-tweets-48h"
}

def place_order():
    try:
        # print("print market",current_config['market'])
        market = current_config['market']
        seriesSlug = current_config['seriesSlug']
        markets = GetMarkets.get_market(market, seriesSlug)
        print(markets)
        # print(markets['clob_ids'][0])
        # print(markets['condition_id'])



        if markets['isNewMarket'] == True:
            condition_id = markets['condition_id']
            token_id = markets['clob_ids'][0]
            market = markets['market']
            side = current_config['side']
            size = current_config['size']
            price = current_config['price']
            print("here", side, size, price)
            # OrderExecutor.execute_strategy(condition_id, tokenId, 5.10)
            try:
                order_id = OrderExecutor.place_limit_order(token_id, price, size, "BUY")
                print("===============")
                Notifier.notify_trade(market, side, size, price, order_id)
                

            except Exception as e:
                Notifier.notify_error("Failed Executing Limit Order")
                print(f"❌ Error de conexión: {e}")
            
        else:
            print("No New Market To Bet")
            # message = Notifier.check_for_commands()
            # print("message")

    except Exception as e:
        print(f"❌ Error de conexión: {e}")

# Global instance

def parse_set_order_limit(order):

    parts = order
    # command = parts[0].lower() # "/set", "/start", etc.

    if len(parts) == 5:
        try:
            new_side = parts[1].upper() # "BUY"
            raw_size = parts[2].replace(',', '.').strip()
            raw_price = parts[3].replace(',', '.').strip()
            new_market = f"{parts[4]}"


            new_size = float(raw_size)  # 50.0
            new_price = float(raw_price) # 0.90
                            
            # Actualizamos la memoria global
            current_config["side"] = new_side
            current_config["size"] = new_size
            current_config["price"] = new_price
            current_config["market"] = new_market
                            
            msg = f"✅ New order limit information set:\nSide: {new_side}\nSize: {new_size}\nPrice: {new_price}\nMarket: {new_market}"
            print(msg)
            Notifier._send(msg) # Confirma en Telegram

            # return {"newSide": new_side, "new_size": new_size, "new_price": new_price}
        except ValueError:
            Notifier.notify_error("❌ Error: Asegúrate de enviar números válidos para size y price.")
    else:
        Notifier.notify_error("⚠️ Formato incorrecto. Usa:\n`/order BUY 21 0.05`")

def cycle():
    current_state = "RUNNING"
    # print("🚀 Iniciando Bot de Polymarket...")
    # print("Presiona Ctrl+C para detenerlo.")
    WAIT_TIME_SECONDS = 2 # Recomendado subir esto

    try:
        while True:
            try:
                cmd_text = command_queue.get_nowait()
                parts = cmd_text.split()
                new_command = parts[0].lower()

                if new_command == "/stop":
                    current_state = "STOPPED"
                    Notifier._send("Pausing operations...")
                    print("🛑 Pausing operations...")
                elif new_command == "/set":
                    parse_set_order_limit(parts)
                elif new_command == "/start":
                    current_state = "RUNNING"
                    Notifier._send("Starting operations")
                    print("✅ Reanudando operaciones...")
            except queue.Empty:
                pass

            if current_state == "RUNNING":
                place_order()
            else:
                print("💤 Zzz... (Pausado)")

            # print(f"⌛ Esperando {WAIT_TIME_SECONDS} segundos...")
            time.sleep(WAIT_TIME_SECONDS)
            
    except KeyboardInterrupt:
        print("\n🔴 Bot detenido por el usuario.")
        sys.exit(0)

t = threading.Thread(target=Notifier.check_for_commands, args=(command_queue,), daemon=True)
t.start()

# print("executer")

# cycle()



# def start_bot():
#     # command_queue.put(Notifier.check_for_commands())

#     while True:
#         try:
#             command = command_queue.get_nowait()
#             if command == "/start":
#                 cycle(command)
#             elif command == "/stop":
#                 cycle(command)
#         except queue.Empty:
#             pass

# start_bot()

# ESTA ES LA CORRECCIÓN CLAVE:
print("1. El archivo se leyó hasta el final.") # <--- Agrega esto

if __name__ == "__main__":
    print("2. Entró al bloque main.") # <--- Agrega esto

else:
    print(f"3. Este archivo fue importado como: {__name__}")