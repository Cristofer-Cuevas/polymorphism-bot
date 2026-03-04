import requests
import json
import re

# CONFIGURACIÓN
TAG_ID_ELON = 972  # El ID mágico que filtra por "Elon Musk" en el backend
REGEX_PATTERN = "Will Elon Musk post 90-114"


def buscar_mercados_elon():
    url = "https://gamma-api.polymarket.com/events"
    
    # 1. Petición optimizada al backend
    # Solo traemos eventos activos que tengan el tag de Elon
    params = {
        "active": "true",
        "closed": "false",
        "tag_id": TAG_ID_ELON, # <--- Aquí está el truc
        "order": "startDate",
        "ascending": "false"
    }
    # seriesSlug elon-tweets-48h

    print(f"📡 Buscando eventos con TAG ID: {TAG_ID_ELON} (Elon Musk)...")
    
    try:
        response = requests.get(url, params=params)
        eventos = response.json()
        
        print(f"✅ Se encontraron {len(eventos)} eventos activos.\n")

        # print(f"✅ Se encontraron {eventos} eventos activos.\n")

        found_tweets = False

        for evento in eventos:

            
            if evento['seriesSlug'] == "elon-tweets-48h": 
                print("startTime", evento['startTime'])
                titulo = evento['title']
                
                # 2. Filtro visual: ¿Es sobre Tweets?
                es_tweet = "tweet" in titulo.lower()
                icono = "🐦" if es_tweet else "🚗"

                es_48 = "elon-tweets-48h" in evento['seriesSlug']
                
                print(f"{icono} EVENTO: {titulo}")
                print(f"   📅 Inicio: {evento['startDate']}")
                
                
                # 3. Iteramos los mercados (las preguntas específicas
                for mercado in evento['markets']:
                    if re.search(REGEX_PATTERN, mercado['question']):
                        print(f"   👉 Pregunta: {mercado['question']}")
                        
                        # Extraemos los precios y los IDs para el bot
                        try:
                            # IDs para operar (Token IDs)
                            clob_ids = json.loads(mercado['clobTokenIds'])
                            precios = json.loads(mercado['outcomePrices'])
                            outcomes = json.loads(mercado['outcomes'])
                            
                            # Mostramos los datos listos para copiar
                            if es_tweet:
                                found_tweets = True
                                print("   🔥 DATOS PARA EL BOT (Copia esto):")
                                for i in range(len(outcomes)):
                                    resultado = outcomes[i]
                                    precio = float(precios[i])
                                    token = clob_ids[i]
                                    print(f"      [{resultado}] Precio: {precio:.2f} | ID: {token}")
                            else:
                                # Si no es de tweets, solo mostramos resumen
                                print(f"      Precios: {outcomes[0]}: {precios[0]} | {outcomes[1]}: {precios[1]}")
                                
                        except:
                            print("      (Error leyendo precios/tokens)")
                
                print("-" * 50)

        if not found_tweets:
            print("\n⚠️ OJO: Encontré eventos de Elon, pero ninguno dice explícitamente 'Tweet' hoy.")

    except Exception as e:
        print(f"❌ Error de conexión: {e}")

if __name__ == "__main__":
    buscar_mercados_elon()