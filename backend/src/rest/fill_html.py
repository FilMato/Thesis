import json
import requests
import os

# Aggiusta il percorso se gs_data si trova in una sottocartella diversa
file_path = os.path.join("..", "..", "..", "gs_data", "dominio_www.mymovies.it_gs.json")

print(f"Leggo il file: {file_path}")

with open(file_path, "r", encoding="utf-8") as f:
    data = json.load(f)

# Fingiamo di essere un browser per non essere bloccati
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

for item in data:
    if not item.get("html_text"):  # Scarica solo se il campo è vuoto
        print(f"Scaricando HTML per: {item['title']}...")
        try:
            response = requests.get(item["url"], headers=headers)
            item["html_text"] = response.text
        except Exception as e:
            print(f"Errore con {item['url']}: {e}")

# Salva il file aggiornato
with open(file_path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("\nFatto! Il tuo file JSON è stato aggiornato con tutti gli HTML grezzi.")