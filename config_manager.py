# import json
# import os
# from datetime import datetime

# class ConfigManager:
#     def __init__(self, file_path="configuration.json"):
#         self.file_path = file_path
#         self.config = {}
#         # FIX: Added parentheses () to actually execute the method
#         self._load_config()

#     def _load_config(self):
#         """Loads JSON into memory. Starts empty if file is missing or corrupt."""
#         if os.path.exists(self.file_path):
#             try:
#                 with open(self.file_path, 'r', encoding='utf-8') as f:
#                     self.config = json.load(f)
#             except json.JSONDecodeError:
#                 print(f"⚠️ Error: The file {self.file_path} is corrupt or malformed.")
#                 self.config = {}
#         else:
#             print(f"⚠️ Alert: {self.file_path} not found. It will be created upon saving.")

#     def _save_changes(self):
#         """Writes changes to JSON file keeping the pretty format."""
#         try:
#             with open(self.file_path, 'w', encoding='utf-8') as f:
#                 # indent=4 ensures readability for manual editing
#                 # ensure_ascii=False supports special characters correctly
#                 json.dump(self.config, f, indent=4, ensure_ascii=False)
#         except Exception as e:
#             print(f"❌ Error saving configuration: {e}")

#     # --- READ METHODS ---

#     def get(self, key, default=None):
#         """Gets a top-level value (e.g., LAST_EVENT_ID)."""
#         return self.config.get(key, default)

#     def get_nested(self, parent_key, child_key, default=None):
#         """Gets a value inside a dictionary (e.g., GET_EVENTS -> TAG_ID_ELON)."""
#         parent = self.config.get(parent_key, {})
        
#         # Check if the parent is actually a dictionary to avoid errors
#         if isinstance(parent, dict):
#             return parent.get(child_key, default)
#         return default 

#     # --- WRITE METHODS ---

#     def update(self, key, value):
#         """Updates or creates a top-level value and saves."""
#         self.config[key] = value
#         self._save_changes()

#     def update_nested(self, parent_key, child_key, value):
#         """Updates a value inside a nested dictionary."""
#         # If parent doesn't exist, create it as a dict
#         if parent_key not in self.config:
#             self.config[parent_key] = {}
        
#         # Ensure parent is a dict before writing
#         if isinstance(self.config[parent_key], dict):
#             self.config[parent_key][child_key] = value
#             self._save_changes()
#         else:
#             print(f"❌ Error: '{parent_key}' exists but is not a dictionary.")

#     def get_last_processed_date(self):
#         """Loads the date string from JSON and converts it to a datetime object."""
#         try:
#             with open(self.file_path, 'r') as f:
#                 data = json.load(f)
#                 date_str = data.get('LAST_EVENT_CREATED_DATE', {})
                
#                 # ⚠️ CRITICAL: Python needs '+00:00' instead of 'Z' for some versions
#                 clean_date_str = date_str.replace("Z", "+00:00")
                
#                 return datetime.fromisoformat(clean_date_str)
#         except FileNotFoundError:
#             # Default to an old date if file doesn't exist
#             return datetime.fromisoformat("2020-01-01T00:00:00+00:00")

#     def update_last_processed_date(self, new_date_obj):
#         """Saves the new latest date back to JSON."""
#         with open(self.file_path, 'r+') as f:
#             data = json.load(f)
#             # Convert object back to string for JSON
#             data['LAST_EVENT_CREATED_DATE'] = new_date_obj.isoformat().replace("+00:00", "Z")
            
#             f.seek(0)
#             json.dump(data, f, indent=4)
#             f.truncate()

# # Global instance for easy import
# config = ConfigManager()



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

    def add_monitored_token(self, token_id, stop_loss, size, price):
        """
        Agrega un token a la lista de vigilancia usando tu lógica existente.
        """
        # 1. Preparamos el paquetito de datos para este token
        data = {
            "stop_loss": float(stop_loss),
            "size": float(size),
            "actual_price": float(price)
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

    def modify_token_stop_loss(self, token_id, new_stop_loss, price):
        """
        Updates the stop_loss value of an already monitored token.
        Preserves the existing 'size' data.
        """
        parent_key = "TOKEN_IDs"
        
        # 1. Load current tokens dictionary
        all_tokens = self.get(parent_key, {})

        # 2. Verify the token actually exists in the monitoring list
        if token_id in all_tokens:
            # 3. Update ONLY the stop_loss
            all_tokens[token_id]["stop_loss"] = float(new_stop_loss)
            all_tokens[token_id]["actual_price"] = float(price)
            
            # 4. Save the whole dictionary back to the DB
            self.update(parent_key, all_tokens)
            
            print(f"✏️ Config updated: Token {token_id[:10]}... new Stop Loss is ${new_stop_loss}")
            return True
        else:
            print(f"⚠️ Cannot modify: Token {token_id[:10]}... is not currently being monitored.")
            return False

# Global instance
config = ConfigManager()