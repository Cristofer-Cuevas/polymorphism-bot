import requests
import json
import re
from config_manager import config
from datetime import datetime
from notification_manager import Notifier

# CONFIGURACIÓN
TAG_ID_ELON = 972  # El ID mágico que filtra por "Elon Musk" en el backend
REGEX_PATTERN = "Will Elon Musk post 90-114"
LAST_ID = ""
LAST_EVENT_INDEX: int


class GetMarkets():
    def __init__(self):
        self.url = "https://gamma-api.polymarket.com/events"
    
        # 1. Petición optimizada al backend
        # Solo traemos eventos activos que tengan el tag de Elon
        self.params = {
            "active": "true",
            "closed": "false",
            "tag_id": config.get_nested("GET_EVENTS", "TAG_ID_ELON"),
            "order": "startDate",
            "ascending": "true"
        }
        # seriesSlug elon-tweets-48h
        self.tag_elon = config.get_nested("GET_EVENTS", "TAG_ID_ELON")
    
    # print(tag_elon)

    print(f"📡 Buscando eventos con TAG ID: {TAG_ID_ELON} (Elon Musk)...")

    def get_market(self, market, seriesSlug):
        # print("ntou")
        try:
            response = requests.get(self.url, params=self.params)
            eventos = response.json()
            
            # print(f"✅ Se encontraron {len(eventos)} eventos activos.\n")

            # print(f"✅ Se encontraron {eventos} eventos activos.\n")

            # eventos.sort(key=lambda x: x['createdAt'])

            found_tweets = False
            isNewMarket = False

            for index, evento in enumerate(eventos):
                
                if evento['seriesSlug'] == seriesSlug: 
                    
                    titulo = evento['title']
                    
                    if evento.get('startDate') is None:
                        continue

                    # print(config.get_nested("SET_LAST_EVENT_INFO", "LAST_EVENT_ID"))
                    last_event_date = config.get_last_processed_date()
                    created_at_event = datetime.fromisoformat(evento['createdAt'].replace("Z", "+00:00"))
                    # converter = datetime.fromisoformat(created_at_event)
                    # print("converter", converter)

                    print(created_at_event, last_event_date)
                    
                    if created_at_event > last_event_date:
                        print("startTime", evento['startTime'])
                        print("DATES:",last_event_date, created_at_event)
                        
                        config.update_nested("SET_LAST_EVENT_INFO", "LAST_EVENT_ID", evento['id'])
                        # config.update_last_processed_date(datetime.fromisoformat(evento['createdAt'].replace("Z", "+00:00")))
                        print("NEW DATE:::", datetime.fromisoformat(evento['createdAt'].replace("Z", "+00:00")))
                        # print(config.get_nested("SET_LAST_EVENT_INFO", "LAST_EVENT_ID"), evento['id'])
                        
                        es_tweet = "tweet" in titulo.lower()
                        icono = "🐦" if es_tweet else "🚗"

                        print(f"{icono} EVENTO: {titulo}")
                        print(f"   📅 Inicio: {evento['startDate']}")
                        print(f"   📅 InicioID: {evento['id']}")


                        for mercado in evento['markets']:
                            if re.search(config.get_nested('GET_EVENTS', market), mercado['question']):
                                print(f"   👉 Pregunta: {mercado['question']}")
                                
                                if not mercado['conditionId']:
                                    print("⏳ Skipping newly created market: 'condition_id' not yet available on the API.")
                                    continue  # Move on to the next market in the loop

                                Notifier.notify_new_event(evento['title'], evento['createdAt'])
                                config.update_last_processed_date(datetime.fromisoformat(evento['createdAt'].replace("Z", "+00:00")))
                                isNewMarket = True
                                condition_id = mercado['conditionId']
                                

                                
                                # Extraemos los precios y los IDs para el bot
                                try:
                                    # IDs para operar (Token IDs)
                                    clob_ids = json.loads(mercado['clobTokenIds'])
                                    prices = json.loads(mercado['outcomePrices'])
                                    outcomes = json.loads(mercado['outcomes'])
                                    
                                    # Mostramos los datos listos para copiar
                                    # if es_tweet:
                                    #     found_tweets = True
                                    #     print("   🔥 DATOS PARA EL BOT (Copia esto):")
                                    #     for i in range(len(outcomes)):
                                    #         result = outcomes[i]
                                    #         price = float(prices[i])
                                    #         token = clob_ids[i]
                                    #         print(f"      [{result}] Precio: {price:.2f} | ID: {token}")
                                    # else:
                                    #     # Si no es de tweets, solo mostramos resumen
                                    #     print(f"      Prices: {outcomes[0]}: {prices[0]} | {outcomes[1]}: {prices[1]}")
                                    
                                    return {
                                        "clob_ids": clob_ids,
                                        "prices": prices, 
                                        "outcomes": outcomes,
                                        "condition_id": condition_id,
                                        "isNewMarket": isNewMarket,
                                        "market": mercado['question']
                                        }
                                        
                                except:
                                    print("      (Error leyendo precios/tokens)")
                        
                        print("-" * 50)

                        break
                    
                    # # 2. Filtro visual: ¿Es sobre Tweets?
                    # es_tweet = "tweet" in titulo.lower()
                    # icono = "🐦" if es_tweet else "🚗"

                    # # es_48 = "elon-tweets-48h" in evento['seriesSlug']
                    
                    # print(f"{icono} EVENTO: {titulo}")
                    # print(f"   📅 Inicio: {evento['startDate']}")
                    # print(f"   📅 InicioID: {evento['id']}")
                    
                    
                    # # 3. Iteramos los mercados (las preguntas específicas
                    # for mercado in evento['markets']:
                    #     # print("here")
                    #     if re.search(config.get_nested('GET_EVENTS', "MARKET_90-114"), mercado['question']):
                    #         print(f"   👉 Pregunta: {mercado['question']}")
                            
                    #         # Extraemos los precios y los IDs para el bot
                    #         try:
                    #             # IDs para operar (Token IDs)
                    #             clob_ids = json.loads(mercado['clobTokenIds'])
                    #             precios = json.loads(mercado['outcomePrices'])
                    #             outcomes = json.loads(mercado['outcomes'])
                                
                    #             # Mostramos los datos listos para copiar
                    #             if es_tweet:
                    #                 found_tweets = True
                    #                 print("   🔥 DATOS PARA EL BOT (Copia esto):")
                    #                 for i in range(len(outcomes)):
                    #                     resultado = outcomes[i]
                    #                     precio = float(precios[i])
                    #                     token = clob_ids[i]
                    #                     print(f"      [{resultado}] Precio: {precio:.2f} | ID: {token}")
                    #             else:
                    #                 # Si no es de tweets, solo mostramos resumen
                    #                 print(f"      Precios: {outcomes[0]}: {precios[0]} | {outcomes[1]}: {precios[1]}")
                                    
                    #         except:
                    #             print("      (Error leyendo precios/tokens)")
                    
                    print("-" * 50)

            # if not found_tweets:
            #     print("\n⚠️ OJO: Encontré eventos de Elon, pero ninguno dice explícitamente 'Tweet' hoy.")

            return {"isNewMarket": isNewMarket}

        except Exception as e:
            print(f"❌ Error de conexión: {e}")

            


GetMarkets = GetMarkets()