
import sqlite3
import json
from datetime import datetime

class ConfigManager:
    def __init__(self, db_path="bot_memory.db"):
        self.db_path = db_path
        # check_same_thread=False allows using this connection in different functions safely
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._init_db()

    def _init_db(self):
        """
        Creates the table if it doesn't exist.
        We use a simple Key-Value structure to mimic the JSON flexibility.
        """
        try:
            with self.conn:
                self.conn.execute("""
                    CREATE TABLE IF NOT EXISTS bot_state (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    )
                """)
        except sqlite3.Error as e:
            print(f"❌ Critical Database Error: {e}")

    # --- GENERIC READ METHODS ---

    def get(self, key, default=None):
        """
        Gets a top-level value.
        Automatically deserializes JSON (strings -> dicts/lists/ints).
        """
        cursor = self.conn.cursor()
        try:
            cursor.execute("SELECT value FROM bot_state WHERE key = ?", (key,))
            row = cursor.fetchone()
            
            if row:
                # We stored it as JSON string, so we load it back to Python object
                return json.loads(row[0])
            return default
        except Exception as e:
            print(f"⚠️ Error reading key '{key}': {e}")
            return default

    def get_nested(self, parent_key, child_key, default=None):
        """
        Gets a value inside a dictionary stored in the DB.
        """
        # 1. Get the whole parent dictionary
        parent_data = self.get(parent_key, {})
        
        # 2. Navigate inside
        if isinstance(parent_data, dict):
            return parent_data.get(child_key, default)
        return default

    # --- GENERIC WRITE METHODS ---

    def update(self, key, value):
        """
        Updates or Inserts a value (UPSERT).
        Automatically serializes Python objects to JSON strings.
        """
        try:
            # Convert python object (dict, list, int) to string for storage
            json_val = json.dumps(value)
            
            with self.conn:
                # INSERT OR REPLACE is the magic SQLite command for "Update if exists, Create if not"
                self.conn.execute(
                    "INSERT OR REPLACE INTO bot_state (key, value) VALUES (?, ?)", 
                    (key, json_val)
                )
        except Exception as e:
            print(f"❌ Error updating key '{key}': {e}")

    def update_nested(self, parent_key, child_key, value):
        """
        Updates a value inside a nested dictionary.
        Logic: Read Parent -> Modify Python Dict -> Write Parent Back
        """
        # 1. Get current state of parent
        parent_data = self.get(parent_key, {})
        
        # 2. Ensure it's a dictionary
        if not isinstance(parent_data, dict):
            parent_data = {}

        # 3. Update the specific child key
        parent_data[child_key] = value

        # 4. Save the whole thing back to DB
        self.update(parent_key, parent_data)

    # --- SPECIFIC DATE METHODS (The most important part) ---

    def get_last_processed_date(self):
        """
        Retrieves the last event date safely.
        """
        date_str = self.get('LAST_EVENT_CREATED_DATE')

        if not date_str:
            # Fallback if DB is empty
            return datetime.fromisoformat("2020-01-01T00:00:00+00:00")

        try:
            # ⚠️ Clean the string just in case
            clean_date_str = date_str.replace("Z", "+00:00")
            return datetime.fromisoformat(clean_date_str)
        except ValueError:
            print(f"⚠️ Corrupt date format found: {date_str}. Resetting to default.")
            return datetime.fromisoformat("2020-01-01T00:00:00+00:00")

    def update_last_processed_date(self, new_date):
        """
        Saves the new latest date. Accepts String or Datetime object.
        """
        if isinstance(new_date, str):
            date_str = new_date
        else:
            # Convert datetime object to string
            date_str = new_date.isoformat().replace("+00:00", "Z")
            
        self.update('LAST_EVENT_CREATED_DATE', date_str)
        print(f"💾 Checkpoint saved: {date_str}")

    def add_monitored_token(self, token_id, stop_loss, size, price, slug, is_one_left):
        """
        Agrega un token a la lista de vigilancia usando tu lógica existente.
        """
        # 1. Preparamos el paquetito de datos para este token
        data = {
            "stop_loss": float(stop_loss),
            "size": float(size),
            "actual_price": float(price),
            "is_active": True,
            "bracket": slug,
            "is_one_left": is_one_left
        }
        
        # 2. Usamos tu función mágica 'update_nested'
        # Ella sola se encarga de leer la DB, actualizar el JSON y guardar.
        # Parent Key: "TOKEN_IDs" | Child Key: El Token ID
        self.update_nested("TOKEN_IDs", token_id, data)
        
        print(f"✅ Config guardada: Token {token_id} añadido.")

    def remove_monitored_token(self, token_id):
        """
        Removes a specific token from the 'TOKEN_IDs' list in the database.
        Call this after selling a position to stop monitoring it.
        """
        parent_key = "TOKEN_IDs"
        
        # 1. Load current data
        current_data = self.get(parent_key, {})

        # 2. Check if token exists
        if token_id in current_data:
            # 3. Delete the key
            del current_data[token_id]
            
            # 4. Save the updated dict back to DB
            self.update(parent_key, current_data)
            print(f"🗑️ Config updated: Token {token_id[:15]}... removed from monitoring.")
            return True
        else:
            print(f"⚠️ Token {token_id[:15]}... was not found in monitoring list.")
            return False

    def modify_token_stop_loss(self, short_token_id, new_stop_loss, price=None):
        """
        Updates the stop_loss value of an already monitored token by matching 
        the last 5 characters of its ID. Preserves 'actual_price' and 'size'.
        """
        parent_key = "TOKEN_IDs"
        
        # 1. Load current tokens dictionary
        all_tokens = self.get(parent_key, {})

        # 2. Search for the full token ID using the last 5 charactersh
        matched_full_id = None
        
        # Ensure we are comparing strings and extract exactly the last 5 chars.
        # This protects the logic even if the full ID is accidentally passed.
        search_suffix = str(short_token_id)[-5:] 
        
        for full_id in all_tokens.keys():
            if str(full_id).endswith(search_suffix):
                matched_full_id = full_id
                break  # Stop searching instantly once the match is found

        # 3. Verify if a match was successfully found in the loop
        if matched_full_id:
            
            try:
                # Update using the FULL ID, not the 5-digit suffix
                all_tokens[matched_full_id]["stop_loss"] = float(new_stop_loss)
            except (ValueError, TypeError):
                print(f"❌ Error: Invalid stop_loss format provided for ...{search_suffix}")
                return False

            if price is not None:
                try:
                    all_tokens[matched_full_id]["actual_price"] = float(price)
                except (ValueError, TypeError):
                    print(f"⚠️ Warning: Invalid price format ignored for ...{search_suffix}")
            
            # 4. Save the mutated dictionary back to the DB
            self.update(parent_key, all_tokens)
            
            print(f"✏️ Config updated: Token ...{search_suffix} new Stop Loss is ${new_stop_loss}")
            return True
            
        else:
            print(f"⚠️ Cannot modify: No token ending in '...{search_suffix}' is currently being monitored.")
            return False

    def get_stop_loss_threshold(self, default=0.15):
        """
        Retrieves the master stop loss threshold from the DB.
        If it doesn't exist yet, it returns the provided default.
        """
        # Uses the existing generic 'get' method
        value = self.get("STOP_LOSS_THRESHOLD", default)
        return float(value)

    def update_stop_loss_threshold(self, new_threshold):
        """
        Updates the master stop loss threshold in the database.
        """
        # Uses the existing generic 'update' method
        self.update("STOP_LOSS_THRESHOLD", float(new_threshold))
        print(f"⚙️ DB Update: Global Stop Loss Threshold permanently set to {new_threshold}")

    def is_token_monitored(self, token_id: str) -> bool:
        """
        Checks if a specific token_id is currently stored in the database's monitoring list.
        
        Args:
            token_id (str): The unique Polymarket identifier to verify.
            
        Returns:
            bool: True if the token exists in the database, False otherwise.
        """
        # Retrieve the master dictionary of all active tokens from SQLite
        active_tokens = self.get("TOKEN_IDs", {})
        
        # Evaluate and return whether the provided token_id exists as a key
        return token_id in active_tokens

    def remove_inactive_tokens(self) -> int:
        """
        Scans the master token list and permanently removes any token 
        where the 'is_active' flag evaluates to False.
        
        Returns:
            int: The total number of tokens removed from the database.
        """
        parent_key = "TOKEN_IDs"
        
        # 1. Load the entire token dictionary from SQLite
        all_tokens = self.get(parent_key, {})
        
        if not all_tokens:
            print("📭 Token database is empty. No cleanup required.")
            return 0

        # 2. Safely filter out inactive tokens using dictionary comprehension.
        # We use .get("is_active", True) to default to True just in case 
        # a token is missing the key, preventing accidental deletions.
        active_tokens_only = {
            token_id: token_data 
            for token_id, token_data in all_tokens.items() 
            if token_data.get("is_active", True) is True
        }

        # 3. Calculate how many tokens were actually filtered out
        tokens_removed_count = len(all_tokens) - len(active_tokens_only)

        # 4. Save to the database ONLY if a change occurred to save I/O operations
        if tokens_removed_count > 0:
            self.update(parent_key, active_tokens_only)
            print(f"🧹 Cleanup complete: {tokens_removed_count} inactive token(s) permanently removed from DB.")
        else:
            print("✅ Database is clean: No inactive tokens found.")
            
        return tokens_removed_count
    
    def remove_by_token_id(self, suffix: str) -> bool:
        """
        Searches for a token ID that ends with the provided suffix (e.g., last 6 digits)
        and permanently removes it from the monitoring database.
        
        Args:
            suffix (str): The last characters of the token ID to search for.
            
        Returns:
            bool: True if at least one token was found and removed, False otherwise.
        """
        parent_key = "TOKEN_IDs"
        
        # 1. Load the entire token dictionary from SQLite
        all_tokens = self.get(parent_key, {})
        
        if not all_tokens:
            print("📭 Token database is currently empty.")
            return False

        # 2. Identify all keys that match the requested suffix
        # We cast both to string to prevent TypeError crashes
        target_suffix = str(suffix)
        keys_to_delete = [
            token_id for token_id in all_tokens.keys() 
            if str(token_id).endswith(target_suffix)
        ]

        # 3. Handle the case where no match is found
        if not keys_to_delete:
            print(f"⚠️ Cannot remove: No token found ending with '{target_suffix}'.")
            return False

        # 4. Safely delete the matched keys from the dictionary
        for key in keys_to_delete:
            del all_tokens[key]
            print(f"🗑️ Config updated: Token ending in ...{key[-5:]} has been removed.")

        # 5. Save the modified dictionary back to the database
        self.update(parent_key, all_tokens)
        return True

    def toggle_token_monitoring(self, suffix: str, toggle_key: str) -> str:
        """
        Searches for a token ID ending with the provided suffix (e.g., last 6 digits)
        and toggles its 'is_active' boolean status.
        
        Args:
            suffix (str): The trailing characters of the token ID to target.
            toggle_key (str): The key whose value needs to be toggled.
            
        Returns:
            str: A message indicating the result of the operation.
        """
        parent_key = "TOKEN_IDs"
        
        # 1. Load the entire token dictionary from the SQLite database
        all_tokens = self.get(parent_key, {})
        
        if not all_tokens:
            print("📭 Token database is currently empty.")
            return False

        # 2. Identify all keys matching the requested suffix
        target_suffix = str(suffix)
        matched_keys = [
            token_id for token_id in all_tokens.keys() 
            if str(token_id).endswith(target_suffix)
        ]

        # 3. Handle the case where the token does not exist
        if not matched_keys:
            print(f"⚠️ Cannot update: No token found ending with '{target_suffix}'.")
            return False

        message = ""

        # 4. Safely toggle the boolean flag for the matched keys
        for key in matched_keys:
            # Extract current status, defaulting to True if the key is somehow missing
            current_status = all_tokens[key].get(toggle_key, True)

            # Invert the boolean value
            new_status = not current_status
            all_tokens[key][toggle_key] = new_status
            
            # Formatted console logging for server monitoring
            status_icon = "🟢" if new_status else "🔴"
            state_text = "ACTIVE" if new_status else "INACTIVE"
            if toggle_key == "is_active":
                message = f"{status_icon} Token ...{key[-5:]} is now {state_text}."
            else:
                message = f"{status_icon} Token ...{key[-5:]} 'is_one_left' is now {state_text}."
            # print(f"{status_icon} Config updated: Token ...{key[-5:]} is now {state_text}.")

        # 5. Commit the modified dictionary back to the database memory
        self.update(parent_key, all_tokens)
        return message

# Global instance
config = ConfigManager()