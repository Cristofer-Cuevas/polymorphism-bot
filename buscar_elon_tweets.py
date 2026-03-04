import requests
import json

def buscar_mercados_elon():
    # 1. Buscamos eventos activos
    url = "https://gamma-api.polymarket.com/events"
    params = {
        "limit": 100,       # Traemos bastantes para asegurar que salga
        "active": "true",   # Solo activos
        "closed": "false",
        "order": "startDate", # Los más recientes primero
        "ascending": "false"
    }

    print("🛰️ Escaneando Polymarket en busca de Elon Musk...")
    
    try:
        response = requests.get(url, params=params)
        data = response.json()
        
        encontrado = False

        for evento in data:
            # FILTRO: Buscamos "Elon" Y "Tweet" en el título
            titulo = evento['title'].lower()
            if "elon" in titulo and "tweet" in titulo:
                encontrado = True
                print("\n" + "🎯"*15)
                print(f"EVENTO ENCONTRADO: {evento['title']}")
                print(f"ID del Evento: {evento['id']}")
                print("🎯"*15)

                # Ahora listamos los RANGOS (Markets) disponibles
                print("\n📦 RANGOS DISPONIBLES (Copia el 'Asset ID' del que quieras comprar):")
                
                for mercado in evento['markets']:
                    # Limpiamos la pregunta para que se vea bonita
                    pregunta = mercado['question']
                    
                    # Extraemos los IDs para operar (Token IDs)
                    # clobTokenIds suele ser ["ID_NO", "ID_YES"]
                    token_ids = json.loads(mercado['clobTokenIds'])
                    id_yes = token_ids[1] # El ID para comprar "SÍ"
                    
                    # Precios actuales
                    precios = json.loads(mercado['outcomePrices'])
                    precio_yes = float(precios[1])

                    print(f"\n   👉 Opción: {pregunta}")
                    print(f"      💰 Precio 'YES': ${precio_yes:.2f} ({precio_yes*100:.1f}%)")
                    print(f"      🔑 ASSET ID (Para el Bot): {id_yes}")
                    print("      " + "-"*30)
        
        if not encontrado:
            print("❌ No se encontraron mercados activos de 'Elon Tweets' esta semana.")
            print("(A veces tardan en abrir el mercado de la semana siguiente los lunes/martes).")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    buscar_mercados_elon()