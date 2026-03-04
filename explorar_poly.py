import requests
import json

def explorar_mercados():
    # Endpoint oficial de lectura (Gamma)
    url = "https://gamma-api.polymarket.com/events"
    
    # Parámetros: Queremos mercados activos, ordenados por volumen
    params = {
        "limit": 5,          # Solo los top 5
        "active": "true",    # Que no hayan terminado
        "closed": "false",
        "order": "volume",   # Los que mueven más dinero
        "ascending": "false" # De mayor a menor
    }

    print("📡 Conectando a Polymarket Gamma API...")
    response = requests.get(url, params=params)
    
    if response.status_code == 200:
        data = response.json()
        
        for evento in data:
            print(f"\n📢 EVENTO: {evento['title']}")
            # Un evento puede tener varios mercados (ej: Ganador, Margen, etc.)
            # Vamos a ver el primer mercado del evento
            mercado = evento['markets'][0]
            print(f"   🔹 Pregunta: {mercado['question']}")
            print(f"   💰 Volumen: ${float(mercado['volume']):,.2f}")
            
            # Lo más importante para el bot: EL PRECIO DE LOS RESULTADOS
            try:
                outcomes = json.loads(mercado['outcomes']) # ["Yes", "No"]
                prices = json.loads(mercado['outcomePrices']) # ["0.65", "0.35"]
                
                print("   📊 Precios actuales:")
                for outcome, price in zip(outcomes, prices):
                    print(f"      - {outcome}: {float(price)*100:.1f}% (${price})")
            except:
                print("      (Formato de precios complejo)")
    else:
        print("❌ Error:", response.status_code)

if __name__ == "__main__":
    explorar_mercados()