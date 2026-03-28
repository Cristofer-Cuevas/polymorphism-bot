import requests
import json
import re
from config_manager import config
from datetime import datetime
from notification_manager import Notifier

TAG_ID_ELON = 972
REGEX_PATTERN = "Will Elon Musk post 90-114"
LAST_ID = ""
LAST_EVENT_INDEX: int


class GetMarkets():
    def __init__(self):
        self.url = "https://gamma-api.polymarket.com/events"
        self.params = {
            "active": "true",
            "closed": "false",
            "tag_id": config.get_nested("GET_EVENTS", "TAG_ID_ELON"),
            "order": "startDate",
            "ascending": "true",
            "limit": 100
        }
        self.tag_elon = config.get_nested("GET_EVENTS", "TAG_ID_ELON")

    print(f"📡 Buscando eventos con TAG ID: {TAG_ID_ELON} (Elon Musk)...")

    def get_market(self, market, seriesSlug):
        try:
            response = requests.get(self.url, params=self.params)
            eventos = response.json()

            found_tweets = False
            isNewMarket = False

            for index, evento in enumerate(eventos):

                if evento.get('seriesSlug') == seriesSlug:

                    titulo = evento['title']

                    if evento.get('startDate') is None:
                        continue

                    last_event_date = config.get_last_processed_date()
                    created_at_event = datetime.fromisoformat(evento['createdAt'].replace("Z", "+00:00"))

                    if created_at_event > last_event_date:
                        print("startTime", evento['startTime'])
                        print("DATES:", last_event_date, created_at_event)

                        config.update_nested("SET_LAST_EVENT_INFO", "LAST_EVENT_ID", evento['id'])
                        print("NEW DATE:::", datetime.fromisoformat(evento['createdAt'].replace("Z", "+00:00")))

                        es_tweet = "tweet" in titulo.lower()
                        icono = "🐦" if es_tweet else "🚗"

                        print(f"{icono} EVENTO: {titulo}")
                        print(f"   📅 Inicio: {evento['startDate']}")
                        print(f"   📅 InicioID: {evento['id']}")

                        for market_index, mercado in enumerate(evento['markets']):
                            if re.search(config.get_nested('GET_EVENTS', market), mercado['question']):
                                print(f"   👉 Pregunta: {mercado['question']}")

                                if not mercado['conditionId']:
                                    print("⏳ Skipping newly created market: 'condition_id' not yet available on the API.")
                                    continue

                                Notifier.notify_new_event(evento['title'], evento['createdAt'])
                                config.update_last_processed_date(datetime.fromisoformat(evento['createdAt'].replace("Z", "+00:00")))
                                isNewMarket = True
                                condition_id = mercado['conditionId']

                                try:
                                    clob_ids = json.loads(mercado['clobTokenIds'])
                                    prices = json.loads(mercado['outcomePrices'])
                                    outcomes = json.loads(mercado['outcomes'])

                                    return {
                                        "clob_ids": clob_ids,
                                        "prices": prices,
                                        "outcomes": outcomes,
                                        "condition_id": condition_id,
                                        "isNewMarket": isNewMarket,
                                        "market": mercado['question'],
                                        "neg_risk_market_id": evento.get('negRiskMarketID'),
                                        "market_index": market_index,
                                        "api_condition_id": condition_id
                                    }

                                except:
                                    print("      (Error leyendo precios/tokens)")

                        print("-" * 50)
                        break

            return {"isNewMarket": isNewMarket}

        except Exception as e:
            print(f"❌ Error de conexión: {e}")

    def get_active_bracket(self, bracket, seriesSlug):
        """
        Gets YES token ID for a specific bracket in the current active event.
        No date check — returns data from any active event matching seriesSlug.
        Used by /set_next_buy to pre-cache token data for instant tweet buys.
        """
        try:
            response = requests.get(self.url, params=self.params)
            eventos = response.json()

            for evento in eventos:
                if evento.get('seriesSlug') != seriesSlug:
                    continue
                if evento.get('startDate') is None:
                    continue

                for mercado in evento['markets']:
                    if re.search(config.get_nested('GET_EVENTS', bracket), mercado['question']):
                        if not mercado['conditionId']:
                            continue
                        clob_ids = json.loads(mercado['clobTokenIds'])
                        return {
                            "yes_token_id": clob_ids[0],
                            "market": mercado['question'],
                        }
            return None

        except Exception as e:
            print(f"❌ Error fetching active bracket: {e}")
            return None

    def get_active_market(self, bracket, seriesSlug):
        """
        Gets full market data (NO token, condition_id, neg_risk_market_id) for a bracket.
        No date check — used by /buy_no to manually trigger buy+convert on demand.
        """
        try:
            response = requests.get(self.url, params=self.params)
            eventos = response.json()

            for evento in eventos:
                if evento.get('seriesSlug') != seriesSlug:
                    continue
                if evento.get('startDate') is None:
                    continue

                for mercado in evento['markets']:
                    if re.search(config.get_nested('GET_EVENTS', bracket), mercado['question']):
                        if not mercado['conditionId']:
                            continue
                        clob_ids = json.loads(mercado['clobTokenIds'])
                        return {
                            "no_token_id": clob_ids[1],
                            "condition_id": mercado['conditionId'],
                            "neg_risk_market_id": evento.get('negRiskMarketID'),
                            "market": mercado['question'],
                        }
            return None

        except Exception as e:
            print(f"❌ Error fetching active market: {e}")
            return None


GetMarkets = GetMarkets()
