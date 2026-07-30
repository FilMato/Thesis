import os
import json
import mariadb

# lista dei domini supportati, caricata da un file json, in questo modo se vogliamo aggiungere un dominio basta aggiungerlo al file json senza dover modificare il codice
def _get_supported_domains(base_dir: str) -> list[str]:
    #Se si spostano i file, è necessario aggiornare questo percorso relativo di conseguenza.
    percorso_domains = os.path.join(base_dir, "..", "..", "domains.json")
    try:
        with open(percorso_domains, "r", encoding="utf-8") as f:
            dati_json = json.load(f)
            return dati_json.get("domains", [])
    except FileNotFoundError:
        print("File domains.json non trovato. Uso i domini di fallback.")
        return [
            "www.my-personaltrainer.it",
            "it.wikipedia.org",
            "www.premierleague.com",
            "www.un.org"
        ]

# Scorre i domini supportati e carica in memoria i rispettivi file JSON presenti nella cartella gs_data.
def _load_gold_standard_data(base_dir: str, supported_domains: list[str]) -> dict:
    gs_data = {}
    #Se si spostano i file, è necessario aggiornare questo percorso relativo di conseguenza.
    cartella_gs = os.path.join(base_dir, "..", "..", "gs_data")
    
    if not os.path.exists(cartella_gs):
        print(f"Cartella non trovata: {cartella_gs}")
        return gs_data

    for dominio in supported_domains:
        nome_file = f"dominio_{dominio}_gs.json"    #prendo il nome del file in base al dominio con una stringa formattata, in questo modo se vogliamo aggiungere un dominio basta aggiungere il file con il nome corretto senza dover modificare il codice
        percorso_file = os.path.join(cartella_gs, nome_file)
        try:
            with open(percorso_file, "r", encoding="utf-8") as f:
                gs_data[dominio] = json.load(f)
        except FileNotFoundError:
            print(f"File Gold Standard non trovato per {dominio} ({nome_file})")
    return gs_data

# Esegue le query INSERT IGNORE parametrizzate per un singolo articolo.
def _insert_article(cursor, domain: str, articolo: dict):
    url = articolo.get("url")
    titolo = articolo.get("title", "")
    html = articolo.get("html_text", "")
    gold_text = articolo.get("gold_text", "")
    
    # Inserimento nella tabella padre: web_resources
    query_web = """
        INSERT INTO web_resources (url, domain, title, html_text) 
        VALUES (?, ?, ?, ?)
        ON DUPLICATE KEY UPDATE 
            domain = VALUES(domain),
            title = VALUES(title),
            html_text = VALUES(html_text)
    """
    cursor.execute(query_web, (url, domain, titolo, html))
    
    # Inserimento nella tabella figlia: gold_standard
    query_gs = """
        INSERT INTO gold_standard (url, gold_text) 
        VALUES (?, ?)
        ON DUPLICATE KEY UPDATE 
            gold_text = VALUES(gold_text)
    """
    cursor.execute(query_gs, (url, gold_text))

#Salva il testo estratto dal parser nella tabella parsed_results. Se l'URL è già presente, aggiorna il testo con l'ultima versione estratta.
def save_parsed_result(conn: mariadb.Connection, url: str, parsed_text: str, parser_version: str = "1.0"):
    cursor = conn.cursor()
    try:
        # Inserimento nella tabella parsed_results
        query = """
            INSERT INTO parsed_results (url, parsed_text, parser_version, created_at) 
            VALUES (?, ?, ?, NOW())
            ON DUPLICATE KEY UPDATE 
                parsed_text = VALUES(parsed_text),
                parser_version = VALUES(parser_version),
                created_at = NOW()
        """
        cursor.execute(query, (url, parsed_text, parser_version))
        conn.commit()
        
    except mariadb.Error as e:
        print(f"Errore durante il salvataggio in parsed_results per {url}: {e}")
        conn.rollback()
    finally:
        cursor.close()

#Funzione principale esportata per popolare il database all'avvio.
#Coordina il caricamento dei file e l'inserimento dei dati tramite le funzioni private.
def populate_database(conn: mariadb.Connection):
    # 1. Ottiene i dati dei gold standard dai file JSON
    base_dir = os.path.dirname(os.path.abspath(__file__))
    supported_domains = _get_supported_domains(base_dir)
    gs_domains = _load_gold_standard_data(base_dir, supported_domains)
    if not gs_domains:
        print("Nessun dato Gold Standard trovato da inserire. Termino il seeder.")
        return

    cursor = conn.cursor()
    try:
        # 2. Inserisce i dati iterando sui domini e sugli articoli
        for domain, articoli in gs_domains.items():
            for articolo in articoli:
                _insert_article(cursor, domain, articolo)
        
        # 3. Rende permanenti le modifiche
        conn.commit()
        
    except mariadb.Error as e:
        print(f"Errore durante il popolamento del DB: {e}")
        conn.rollback()
    finally:
        cursor.close()