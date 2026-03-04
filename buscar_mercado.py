import requests
import json

def buscar_mercado(palabra_clave):
    # Usamos el mismo endpoint pero traemos más resultados para filtrar
    url = "https://gamma-api.polymarket.com/events"
    
    params = {
        "limit": 50,        # Traemos 50 para buscar dentro de ello
        "active": "true",   # Solo mercados abiertos
        "closed": "false"   # Que no hayan terminado
    }

    print(f"🔍 Buscando '{palabra_clave}' en Polymarket...")
    
    try:
        response = requests.get(url, params=params)
        data = response.json()
        
        encontrados = 0
        
        for evento in data:
            # Filtro simple de texto (case insensitive)
            if palabra_clave.lower() in evento['title'].lower():
                encontrados += 1
                print("\n" + "="*60)
                print(f"📢 EVENTO: {evento['title']}")
                print(f"   📅 Fecha: {evento['startDate']}")
                
                # Iteramos por los mercados dentro del evento
                for mercado in evento['markets']:
                    print(f"\n   👉 PREGUNTA: {mercado['question']}")
                    
                    # --- ESTE ES EL DATO QUE VALE ORO ---
                    # El 'conditionId' o 'id' es lo que usa el CLOB para operar
                    print(f"   🔑 MARKET ID (Copiar esto): {mercado['id']}")
                    
                    # Mostramos precios para confirmar
                    try:
                        outcomes = json.loads(mercado['outcomes'])
                        prices = json.loads(mercado['outcomePrices'])
                        print(f"   📊 Precios: {outcomes[0]} ({float(prices[0]):.2f}) vs {outcomes[1]} ({float(prices[1]):.2f})")
                    except:
                        pass

        if encontrados == 0:
            print("❌ No se encontraron mercados con esa palabra clave en los top 50.")
            
    except Exception as e:
        print(f"Error de conexión: {e}")

if __name__ == "__main__":
    # --- CAMBIA ESTO PARA PROBAR ---
    keyword = input("¿Qué mercado buscas? (Ej: Elon, Super Bowl, Bitcoin): ")
    buscar_mercado(keyword)