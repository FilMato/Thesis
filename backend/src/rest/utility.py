import os
import json
import re
from pydantic import BaseModel

# Gestione dei domini supportati
base_dir = os.path.dirname(os.path.abspath(__file__))
percorso_domains = os.path.join(base_dir, "..", "..", "domains.json")
try:
    with open(percorso_domains, "r", encoding="utf-8") as f:
        dati_json = json.load(f)
        SUPPORTED_DOMAINS = dati_json.get("domains", [])
except FileNotFoundError:
    SUPPORTED_DOMAINS = [
        "www.my-personaltrainer.it",
        "it.wikipedia.org",
        "www.premierleague.com",
        "www.un.org",
        "www.mymovies.it",
        "www.imdb.com"
    ]


# UTILITY FUNCTIONS:

#Legge un modello Pydantic e crea un dizionario con la stessa struttura inizializzato a 0.0
def Zero_Inizializer(model_class: type[BaseModel]) -> dict:   
    zero_dict = {}
    for field_name, field_info in model_class.model_fields.items():
        key = field_info.alias if field_info.alias else field_name  # Se abbiamo usato un alias (es. "TF-IDF_cosine_similarity") usiamo quello, altrimenti il nome normale
        field_type = field_info.annotation
        if isinstance(field_type, type) and issubclass(field_type, BaseModel):  # Se il campo è un'altra classe Pydantic (es. Metrics o DensityMetrics) facciamo ricorsione
            zero_dict[key] = Zero_Inizializer(field_type)
        else:   # Altrimenti assumiamo che sia un valore singolo e lo mettiamo a 0.0
            zero_dict[key] = 0.0
    return zero_dict

#Funzione per pulire il markdown
def strip_txt(text: str) -> str:
    text = re.sub(r'\*+([^*]+)\*+', r'\1', text) #grassetto
    text = re.sub(r'\_+([^_]+)\_+', r'\1', text) #corsivo
    text = re.sub(r'\#+\s?([^#]+)', r'\1', text) #titoli
    text = re.sub(r'\[([^\]]+)\]\((?:[^)\\]|\\.)*\)', r'\1', text) #link
    return text