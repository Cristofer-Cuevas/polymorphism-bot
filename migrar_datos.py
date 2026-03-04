from config_manager import config

# 1. TUS DATOS CRUDOS (Copiados de tu mensaje)
# Estos son los datos que queremos salvar en la base de datos
datos_json = {
    "GET_EVENTS": {
        "TAG_ID_ELON": 972,
        "<40": "Will Elon Musk post <40",
        "40-64": "Will Elon Musk post 40-64",
        "65-89": "Will Elon Musk post 65-89",
        "90-114": "Will Elon Musk post 90-114",
        "115-139": "Will Elon Musk post 115-139",
        "140-164": "Will Elon Musk post 140-164",
        "165-189": "Will Elon Musk post 165-189",
        "190-214": "Will Elon Musk post 190-214",
        "215-239": "Will Elon Musk post 215-239",
        "240+": "Will Elon Musk post 240+"
    },
    "SET_LAST_EVENT_INFO": {
        "LAST_EVENT_ID": "209120"
    },
    "LIMIT_ORDER_IDs": {
        "20": "0x89a3eff99820f88e98c09c61803f4c06febf0c15587192c848062b25662ae4f5"
    },
    "LAST_EVENT_CREATED_DATE": "2026-02-14T17:00:02.175666Z"
}

def migrar_datos():
    print("🚀 Iniciando migración de JSON a SQLite...")

    # 2. INYECCIÓN DE DATOS
    # Usamos config.update() que maneja automáticamente la conversión a texto para la DB
    
    # A. Guardar la configuración de Eventos (Diccionario completo)
    print("📦 Migrando GET_EVENTS...")
    config.update("GET_EVENTS", datos_json["GET_EVENTS"])

    # B. Guardar info del último evento
    print("📦 Migrando SET_LAST_EVENT_INFO...")
    config.update("SET_LAST_EVENT_INFO", datos_json["SET_LAST_EVENT_INFO"])

    # C. Guardar IDs de órdenes (Historial)
    print("📦 Migrando LIMIT_ORDER_IDs...")
    config.update("LIMIT_ORDER_IDs", datos_json["LIMIT_ORDER_IDs"])

    # D. Guardar la fecha (La más importante para tu estrategia)
    print("📅 Migrando Fecha de Creación...")
    config.update("LAST_EVENT_CREATED_DATE", datos_json["LAST_EVENT_CREATED_DATE"])

    print("\n✅ ¡MIGRACIÓN COMPLETADA CON ÉXITO!")
    print("------------------------------------------------")
    
    # 3. VERIFICACIÓN (Leemos de vuelta para asegurar que se guardó)
    print("🔍 Verificando datos guardados en la DB:")
    fecha_guardada = config.get_last_processed_date()
    eventos_guardados = config.get("GET_EVENTS")
    
    print(f"   -> Fecha en DB: {fecha_guardada}")
    print(f"   -> ID de Elon Tag: {eventos_guardados.get('TAG_ID_ELON')}")

# if __name__ == "__main__":
#     migrar_datos()