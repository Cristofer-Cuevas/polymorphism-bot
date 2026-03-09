import requests
from config_manager import config
# from order_placer import cycles

class NotificationManager:
    def __init__(self):
        # Cargamos las credenciales directamente de la DB al iniciar
        self.token = config.get("TELEGRAM_TOKEN")
        self.chat_id = config.get("TELEGRAM_CHAT_ID")
        self.last_update_id = 0
        
        if not self.token or not self.chat_id:
            print("⚠️ ADVERTENCIA: Telegram no está configurado en la DB.")
            self.base_url = None
        else:
            self.base_url = f"https://api.telegram.org/bot{self.token}"

    def _send(self, message):
        """Método interno para enviar la petición HTTP."""
        if not self.base_url:
            return

        try:
            payload = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "Markdown" # Permite usar negritas y estilo
            }
            # Timeout de 5 segundos para no bloquear al bot si internet está lento
            url = f"{self.base_url}/sendMessage"
            response = requests.post(url, data=payload, timeout=5)
            
            if response.status_code != 200:
                print(f"❌ Error Telegram: {response.text}")
                
        except Exception as e:
            print(f"❌ Error de conexión con Telegram: {e}")

    # --- MÉTODOS PÚBLICOS PARA TU BOT ---

    def notify_start(self):
        self._send("🤖 **BOT INICIADO**\n\nEstoy listo para escanear el mercado de Elon Musk. 🚀")

    def notify_trade(self, market_title, side, size, price, order_id):
        """Avisa cuando se ejecuta una orden."""
        emoji = "🟢 BUY" if side == "BUY" else "🔴 SELL"
        
        msg = (
            f"{emoji} **EXECUTED**\n"
            f"-----------------------------\n"
            f"📜 **Market:** {market_title}\n"
            f"🔢 **Size:** {size} acciones\n"
            f"💲 **Price:** ${price}\n"
            f"💰 **Total:** ${round(size * price, 2)}\n"
            f"🆔 `{order_id}`"
        )
        self._send(msg)

    def notify_error(self, error_msg):
        """Avisa si algo grave pasó."""
        self._send(f"⚠️ **ERROR ALERT**\n\n{error_msg}")

    def notify_new_event(self, event_title, created_at):
        """Avisa si encontró un mercado nuevo (Sniper Mode)."""
        self._send(f"🎯 **NEW EVENT DETECTED**\n\n{event_title}\n📅 {created_at}")

    def list_token_ids(self):

        try:
            # Offload the database read operation to a background thread 
            # to prevent freezing the asynchronous Telegram listener
            active_tokens = active_tokens = config.get("TOKEN_IDs", {})
            
            # Handle the edge case where the database is empty
            if not active_tokens:
                self._send("📭 The portfolio is currently empty. No active tokens are being monitored.")
                return

            # Initialize the response array
            response_lines = [f"📊 Active Positions ({len(active_tokens)}):\n"]
            
            # Iterate through the dictionary to format the data
            for token_id, token_data in active_tokens.items():
                # Truncate the long token hash for readability on mobile screens
                short_id = f"{token_id[:4]}...{token_id[-5:]}"
                
                
                # Safely extract the financial metrics
                stop_loss = token_data.get("stop_loss", 0.0)
                size = token_data.get("size", 0.0)
                current_price = token_data.get("actual_price", 0.0)
                bracket = token_data.get("bracket", "Unknown Market")
                status = "🟢 ACTIVE" if token_data.get("is_active", False) else "🔴 INACTIVE"
                
                token_info = (
                    f"🔹 ID: {short_id}\n"
                    f" 💵 Tracked Price: ${current_price}\n"
                    f" 🛑 Stop Loss Limit: ${stop_loss}\n"
                    f" ⚖️ Position Size: {size}\n"
                    f" 🎯 Bracket: {bracket}\n"
                    f" 🎯 Status: {status}\n"
                )
                response_lines.append(token_info)

            # Join all lines and send the consolidated report back to the user
            final_message = "\n".join(response_lines)
            self._send(final_message)
        
        except Exception as e:
            error_msg = f"❌ Database Read Error: {e}"
            message.reply(error_msg)
            print(error_msg)


    def check_for_commands(self, command_queue):

        while True:
            if not self.base_url:
                return None

            url = f"{self.base_url}/getUpdates"
            
            # We ask for updates starting from the last one we saw + 1
            params = {
                "offset": self.last_update_id + 1,
                "timeout": 30  # Don't block the main loop for too long
            }

            try:
                resp = requests.get(url, params=params, timeout=35)
                data = resp.json()
                print("resp", resp)
                if data.get("ok") and data.get("result"):
                    results = data["result"]
                    print("results", results)
                    
                    # If we have results, we process the last one
                    if len(results) > 0:
                        last_msg = results[-1]
                        
                        # Update our offset so we don't read this again
                        self.last_update_id = last_msg["update_id"]

                        # Extract text only if it's a message
                        if "message" in last_msg and "text" in last_msg["message"]:
                            text = last_msg["message"]["text"]
                            sender_id = str(last_msg["message"]["chat"]["id"])
                            command_queue.put(text)

                            # SECURITY: Ignore messages from other people
                            if sender_id != str(self.chat_id):
                                print(f"⚠️ Ignored command from unknown user: {sender_id}")
                                continue

                            print(f"📩 Command received: {text}")
                            # return text
                
                # return None

            except Exception as e:
                print(f"⚠️ Telegram Read Error: {e}")
                return None

Notifier = NotificationManager()




