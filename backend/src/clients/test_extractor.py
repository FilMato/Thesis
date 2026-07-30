import asyncio
import json
import sys
import os
from urllib.parse import urlparse

# Questo assicura che Python trovi i moduli 'src' anche se esegui lo script da un'altra cartella
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from src.factory.parserfactory import ParserFactory
from src.clients import ollama_client

async def main():
    # 1. URL da testare (ho messo uno fittizio di MYmovies per Una battaglia dopo l'altra)
    # Sostituisci questo URL con il link esatto che usi per i tuoi test
    test_url = "https://www.imdb.com/title/tt0332452/" 
    domain = urlparse(test_url).netloc
    
    print(f"Avvio test per il dominio: {domain}")
    print(f"URL: {test_url}\n")

    # 2. Inizializzazione del parser
    try:
        parser = ParserFactory.create(domain)
    except ValueError as e:
        print(f"Errore nell'inizializzare il parser: {e}")
        return

    # 3. Estrazione e pulizia del testo
    print("Scaricamento e pulizia della pagina in corso (Crawl4AI + BeautifulSoup)...")
    risultato_parser = await parser.parser_url(test_url)
    
    testo_pulito = risultato_parser.get("parsed_text", "")
    titolo = risultato_parser.get("title", "Titolo Sconosciuto")

    # STAMPA FONDAMENTALE: Qui verifichi se le recensioni sono state davvero tolte
    print("\n" + "="*50)
    print(" TESTO ESTRATTO DAL PARSER (Controlla che sia breve!)")
    print("="*50)
    print(testo_pulito)
    print("="*50 + "\n")

    if not testo_pulito.strip():
        print("ATTENZIONE: Il parser ha restituito un testo vuoto. Impossibile estrarre le triple.")
        return

    # 4. Estrazione delle triple con Ollama
    print("Invio del testo a Ollama in corso...")
    try:
        # Passiamo il testo pulito e il titolo come da accordi precedenti
        risultato_triple = await ollama_client.extract_triples(testo_pulito)
        
        print("\n" + "="*50)
        print(" TRIPLE ESTRATTE DA OLLAMA")
        print("="*50)
        print(json.dumps(risultato_triple, indent=2, ensure_ascii=False))
        
    except Exception as e:
        print(f"Errore durante l'estrazione delle triple: {e}")

if __name__ == "__main__":
    # Esegue il ciclo asincrono principale
    asyncio.run(main())