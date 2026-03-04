import requests

def buscar_por_backend(nombre_tag):
    gamma_url = "https://gamma-api.polymarket.com"
    
    # 1. Primero encontramos el ID del Tag (esto es rápido, el JSON es pequeño)
    # Polymarket tiene un endpoint de tags
    print(f"🕵️‍♂️ Buscando ID para el tag: '{nombre_tag}'...")
    
    try:
        # Traemos todos los tags (son pocos comparados con los eventos
        resp_tags = requests.get("https://gamma-api.polymarket.com/tags?limit=500")
        tags_data = resp_tags.json()

        print(f"Tags {tags_data}")
        
        tag_id = 6
        for t in tags_data:
            # Comparamos ignorando mayúsculas
            if t['label'].lower() == nombre_tag.lower():
                tag_id = t['id']
                print(f"✅ ¡Encontrado! El ID de '{t['label']}' es: {tag_id}")
                break
        
        if not tag_id:
            print(f"❌ No existe un tag oficial llamado '{nombre_tag}'.")
            return

        # 2. AHORA hacemos la petición filtrada al Backen
        # Aquí es donde ocurre la magia: ?tag_id=XXX
        print("\n🚀 Pidiendo al backend SOLO eventos de este Tag...")
        
        params = {
            "active": "true",
            "new": "true",
            "tag_id": tag_id  # <--- ESTO ES EL FILTRO DE BACKEND
        }
        
        resp_events = requests.get(f"{gamma_url}/events", params=params)
        eventos = resp_events.json()
        
        print(f"📥 El backend nos envió {eventos} eventos limpios.\n")
        
        for e in eventos:
            print(f"👉 {e['title']}")
            # Imprimimos el primer mercado para validar
            if e['markets']:
                print(f"   💰 Precio YES: {e['markets'][0]['outcomePrices'][0]}")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    # Prueba con "Elon Musk", "NFL", "Bitcoin", "Politics"
    buscar_por_backend("musk")