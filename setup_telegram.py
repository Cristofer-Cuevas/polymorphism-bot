from config_manager import config

# --- PON TUS DATOS AQUÍ ---
MI_TOKEN = "8004319389:AAFZzqTYJ20q4_IMBc-szhku8wCZGRzVy2M"  # Ej: "8004319389:AAFZzqTYJ20q4_IMBc-szhku8wCZGRzVy2M"
MI_CHAT_ID = "8004319389"   # Ej: "8004319389"

def guardar_credenciales():
    print("🔐 Guardando credenciales de Telegram en la base de datos...")
    
    # Guardamos en la tabla de configuración
    config.update("TELEGRAM_TOKEN", MI_TOKEN)
    config.update("TELEGRAM_CHAT_ID", MI_CHAT_ID)
    
    # Verificación
    print(f"✅ Token guardado: {config.get('TELEGRAM_TOKEN')[:5]}...")
    print(f"✅ Chat ID guardado: {config.get('TELEGRAM_CHAT_ID')}")
    print("🚀 ¡Listo! Ahora puedes borrar este script si quieres.")

if __name__ == "__main__":
    guardar_credenciales()