import asyncio
from fastapi import APIRouter, Request, HTTPException
from urllib.parse import urlparse
from src.rest.structures import AddToGraphRequest, DeleteGraphRelationRequest, DeleteGraphNodeRequest, AskGraphRequest
from src.rest.utility import SUPPORTED_DOMAINS
from neo.neo4j_client import Neo4jClient
from clients import ollama_client
from src.factory.parserfactory import ParserFactory

router = APIRouter(tags=["Knowledge Graph"])

# Questa funzione gestisce l'intero flusso di elaborazione di un URL: scraping, parsing, salvataggio su MariaDB, estrazione triple con Ollama e inserimento in Neo4j.
async def processa_e_salva_url(conn, url: str, domain: str, testo_esistente: str = None, titolo_esistente: str = ""):
    try:
        print(f"[PROCESS_URL] Inizio elaborazione per: {url}")

        #Se il testo parsato esiste già nel DB, lo usiamo direttamente senza fare scraping, altrimenti facciamo scraping e parsing e salviamo il testo parsato nel DB
        if testo_esistente:
            parsed_text = testo_esistente
            titolo = titolo_esistente
            print(f"[{url}] Salto lo scraping: uso il testo dal DB.")
        else:
            print(f"[{url}] Avvio lo scraping web...")
            # 1. Scraping e Parsing
            parser = ParserFactory.create(domain)
            risultato_parser = await parser.parser_url(url)
            
            if not risultato_parser or not risultato_parser.get("parsed_text"):
                print(f"[PROCESS_URL] ERRORE: Nessun testo estratto da {url}")
                return

            parsed_text = risultato_parser["parsed_text"]
            html_text = risultato_parser.get("html_text", "")
            titolo = risultato_parser.get("title", "")

            # 2. Salvataggio su MariaDB 
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO web_resources (url, domain, title, html_text) 
                VALUES (?, ?, ?, ?)
                ON DUPLICATE KEY UPDATE 
                    domain = VALUES(domain),
                    title = VALUES(title),
                    html_text = VALUES(html_text)
                """,
                (url, domain, titolo, html_text)
            )
            cursor.execute(
                """
                INSERT INTO parsed_results (url, parsed_text, parser_version)
                VALUES (?, ?, ?)
                ON DUPLICATE KEY UPDATE
                    parsed_text = VALUES(parsed_text),
                    parser_version = VALUES(parser_version)
                """,
                (url, parsed_text, "1.0")
            )
            conn.commit()
            cursor.close()
            print(f"[PROCESS_URL] Testo salvato in MariaDB per: {url}")

        # 3. Estrazione Triple con Ollama
        print(f"[PROCESS_URL] Analisi LLM in corso per: {titolo} ({url})")
        risultato_ollama = await ollama_client.extract_triples(parsed_text, titolo)
        
        if "error" in risultato_ollama:
            print(f"[PROCESS_URL] ERRORE Ollama per {url}: {risultato_ollama['error']}")
            return
            
        triple = risultato_ollama.get("triples", [])

        # 4. Inserimento in Neo4j
        if triple:
            with Neo4jClient() as graph_client:
                inserite = graph_client.add_triples_batch(triple)
                print(f"[PROCESS_URL] [OK] Inserite {inserite} triple nel grafo per {url}")
        else:
            print(f"[PROCESS_URL] [WARN] Nessuna tripla estratta da Ollama per {url}")

    except Exception as e:
        print(f"[PROCESS_URL] Errore imprevisto durante l'elaborazione di {url}: {e}")
        if conn:
            conn.rollback() # Annulla modifiche al db se c'è un crash

# Questa funzione interroga MariaDB, passa il testo al client Ollama ed invia il risultato al client Neo4j
async def esegui_pipeline_grafo(conn):
    cursor = conn.cursor()
    
    # 1. Recupera url, titolo e testo parsato da MariaDB
    cursor.execute("""
        SELECT pr.url, wr.title, pr.parsed_text 
        FROM parsed_results pr
        JOIN web_resources wr ON pr.url = wr.url
        WHERE wr.domain IN ('www.mymovies.it', 'www.imdb.com') 
        AND pr.parsed_text IS NOT NULL 
        AND pr.parsed_text != ''
    """)
    documenti = cursor.fetchall()
    cursor.close()

    print(f"Trovati {len(documenti)} documenti da processare per il grafo. Inizio estrazione...")

    with Neo4jClient() as graph_client:
        for row in documenti:
            url = row[0]
            titolo = row[1]     
            testo = row[2]     
            
            print(f"Analisi LLM in corso per: {titolo} ({url})")
            
            # 2. Passiamo ENTRAMBI i parametri a Ollama
            risultato_ollama = await ollama_client.extract_triples(testo, titolo)
            # Gestione di eventuali errori restituiti dal blocco try/except in extract_triples
            if "error" in risultato_ollama:
                print(f"[ERRORE] Ollama ha fallito su {url}: {risultato_ollama['error']}")
                continue
            
            triple = risultato_ollama.get("triples", [])
            
            # 3. Inserisce le triple estratte in Neo4j 
            if triple:
                inserite = graph_client.add_triples_batch(triple)
                print(f"[OK] Inserite {inserite} triple nel grafo per {url}")
            else:
                print(f"[WARN] Nessuna tripla trovata per {url}")
            
            # blocca l'esecuzione per 2 secondi in modo da poter accettare altre richieste ad Ollama invece che dover aspettare che finisca l'elaborazione di tutte le righe
            await asyncio.sleep(2)
            
    print("Pipeline verso Neo4j completata con successo!")

@router.get("/api/graph/visualize")
async def visualize_graph():
    try:
        with Neo4jClient() as graph_client:
            # Recupera un campione di nodi e relazioni dal grafo per la visualizzazione
            query = "MATCH (s)-[r]->(o) RETURN s.name AS subject, labels(s) AS s_labels, type(r) AS relation, o.name AS object, labels(o) AS o_labels LIMIT 200"
            results = graph_client.execute_read_query(query)
            nodes = []
            edges = []
            node_names = set()

            for row in results:
                s, o, r = row.get("subject"), row.get("object"), row.get("relation")
                s_labels, o_labels = row.get("s_labels", []), row.get("o_labels", [])
                s_group = s_labels[0] if s_labels else "Entity"
                o_group = o_labels[0] if o_labels else "Entity"
                #se i nodi non hanno etichette nel DB, le deduciamo dalla relazione
                if s_group == "Entity":
                    if r in ["ACTED_IN", "DIRECTED", "WROTE"]: s_group = "Person"
                    elif r == "HAS_GENRE": s_group = "Movie"
                if o_group == "Entity":
                    if r in ["ACTED_IN", "DIRECTED", "WROTE"]: o_group = "Movie"
                    elif r == "HAS_GENRE": o_group = "Genre"
                    elif r == "WON": o_group = "Award"
                if s not in node_names:
                    nodes.append({"id": s, "label": s, "group": s_group})
                    node_names.add(s)
                if o not in node_names:
                    nodes.append({"id": o, "label": o, "group": o_group})
                    node_names.add(o)

                edges.append({"from": s, "to": o, "label": r})

            return {"nodes": nodes, "edges": edges}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/Add_url_to_graph")
async def Add_url_to_graph(request: AddToGraphRequest, http_request: Request):
    domain = urlparse(request.url).netloc
    if domain not in SUPPORTED_DOMAINS:
        raise HTTPException(status_code=400, detail="Dominio non supportato")
    
    conn = http_request.app.state.db
    if not conn:
        raise HTTPException(status_code=500, detail="Database MariaDB non connesso.")

    # Controlliamo se abbiamo già il testo parsato e il titolo nel database
    cursor = conn.cursor()
    testo_esistente = None
    titolo_esistente = ""
    try:
        cursor.execute(
            """
            SELECT pr.parsed_text, wr.title 
            FROM parsed_results pr
            JOIN web_resources wr ON pr.url = wr.url
            WHERE pr.url = ?
            """, 
            (request.url,)
        )
        record = cursor.fetchone()
        if record:
            testo_esistente = record[0]
            titolo_esistente = record[1]
            print(f"[CACHE HIT] Testo già presente nel DB per {request.url}")
    except Exception as e:
        print(f"Errore durante la lettura da MariaDB: {e}")
    finally:
        cursor.close()
    
    # L'uso di await costringe l'API ad aspettare la fine dell'estrazione
    await processa_e_salva_url(conn, request.url, domain, testo_esistente, titolo_esistente)
   
    return {
        "status": "success", 
        "message": f"Elaborazione dell'URL {request.url} completata e triple aggiunte al grafo."
    }
    

@router.delete("/api/graph/node")
async def Graph_delete_node(request: Request):
    # Leggiamo il body JSON
    data = await request.json()
    node_name = data.get("node_name")
    
    try:
        with Neo4jClient() as graph_client:
            # 1. Controllo esistenza
            check_query = f"MATCH (n {{name: '{node_name}'}}) RETURN n LIMIT 1"
            risultato = graph_client.execute_read_query(check_query)
            
            if not risultato:
                raise HTTPException(status_code=404, detail=f"Impossibile eliminare: il nodo '{node_name}' non esiste nel grafo.")
            
            # 2. Eliminazione 
            delete_query = f"MATCH (n {{name: '{node_name}'}}) DETACH DELETE n"
            graph_client.execute_read_query(delete_query)
            
        return {"status": "success", "message": f"Nodo '{node_name}' e relative relazioni eliminati."}
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
        
@router.delete("/api/graph/relation")
async def Graph_delete_relation(request: DeleteGraphRelationRequest):
    try:
        with Neo4jClient() as graph_client:
            # 1. Controllo esistenza
            check_query = f"MATCH (s {{name: '{request.subject}'}})-[r:`{request.relation}`]->(o {{name: '{request.object}'}}) RETURN r LIMIT 1"
            risultato = graph_client.execute_read_query(check_query)
            
            if not risultato:
                raise HTTPException(status_code=404, detail=f"Impossibile eliminare: la relazione tra '{request.subject}' e '{request.object}' non esiste.")

            # 2. Eliminazione
            graph_client.delete_relation_and_orphans(request.subject, request.relation, request.object)
            
        return {"status": "success", "message": f"Relazione '{request.relation}' eliminata con successo."}
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/build-graph")
async def build_knowledge_graph(http_request: Request):
    conn = http_request.app.state.db
    # await blocca la risposta finché tutti i documenti non sono elaborati
    await esegui_pipeline_grafo(conn)
    
    return {"status": "success", 
            "message": "Knowledge Graph costruito interamente."
            }

@router.post("/api/ask_graph")
async def ask_knowledge_graph(request: AskGraphRequest):
    print(f"[GraphRAG] Domanda ricevuta: {request.question}")
        
    # 1. Generazione query Cypher con Ollama
    cypher_query = await ollama_client.generate_cypher(request.question)
    if not cypher_query:
        raise HTTPException(status_code=500, detail="Impossibile generare la query Cypher.")
    
    print(f"[GraphRAG] Query generata:\n{cypher_query}")
    
    # 2. Esecuzione su Neo4j
    try:
        with Neo4jClient() as graph_client:
            db_results = graph_client.execute_read_query(cypher_query)
    except Exception as e:
            raise HTTPException(status_code=500, detail=f"Errore Neo4j: {str(e)}")
            
    print(f"[GraphRAG] Risultati DB: {db_results}")
    
    # Intercettazione errori Cypher
    if len(db_results) > 0 and "error" in db_results[0]:
        return {
            "question": request.question,
            "cypher_query": cypher_query,
            "raw_data": [],
            "answer": "La domanda è troppo complessa o la query generata non è valida."
        }

    # 3. Formattazione della risposta
    if not db_results:
        final_answer = "Mi dispiace, ma non ho trovato informazioni a riguardo nel Knowledge Graph."
    else:
        elementi = []
        for riga in db_results:
            elementi.append(", ".join([str(v) for v in riga.values()]))
        
        final_answer = "Ecco i risultati trovati nel Knowledge Graph:\n" + "\n".join([f"- {e}" for e in elementi])
    
    return {
        "question": request.question,
        "cypher_query": cypher_query,
        "raw_data": db_results,
        "answer": final_answer
    }