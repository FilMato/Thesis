import asyncio
import httpx
import json
import re
import difflib  # <-- Aggiunto per il Fuzzy Matching (Correzione typos)

URL = "http://ollama:11434/api/generate"
SELECTED_MODEL = "qwen2.5:3b"
MODEL_CYPHER = "qwen2.5-coder:7b" #la traduzione di una domanda testuale in query Cypher richiede un modello più potente, quindi usiamo la versione 7B specializzata per il coding.
MAX_CHARS = 1000

_ollama_lock = asyncio.Lock()
MAX_ATTEMPTS = 2

# --- NUOVA FUNZIONE DI PULIZIA DATE TITOLI ---
def pulisci_date_titoli(testo):
    if not isinstance(testo, str):
        return testo
    # Cerca e cancella qualsiasi blocco tra parentesi contenente almeno un numero 
    # (es. "(1988)", "(2005/I)", "(TV Series 2013-2022)")
    return re.sub(r'\s*\([^)]*\d+[^)]*\)', '', testo).strip()
# ---------------------------------------------


async def judge(parsed_text: str, gold_text: str) -> dict:
    prompt = f"""Act like an expert evaluator of web scraping systems. Your goal is to compare two different texts: 
                 Parsed Text: {parsed_text[:MAX_CHARS]}
                 Gold Text: {gold_text[:MAX_CHARS]}

                 Evaluate their overall score on a scale from 1 to 5. The maximum score (5) means that the Parsed Text is perfectly equal to the Gold Text and contains no extra noise.
                 Perfectly equeal means: equal in length with the Gold Text; equal in phrasing, content, word sequence, capitalization, punctuation.
                 
                 IMPORTANT CONTEXT: The Parsed Text will be consumed by another LLM, not humans. Therefore:
                    - Markdown formatting vs plain text is acceptable (headers ##, bold **, links [] etc.)
                    - Minor differences in spacing, line breaks, or punctuation are negligible
                    - What MATTERS: semantic content preservation, key facts present, logical structure maintained
                    - What's LESS CRITICAL: exact capitalization, minor word reordering that preserves meaning

                SCORING GUIDANCE:
                    - Score 5: All key information present, minimal/no noise, usable by downstream LLM
                    - Score 4: Minor formatting differences or small amount of noise, but content complete
                    - Score 3: Some missing content OR moderate noise, still mostly usable
                    - Score 2: Significant content gaps OR heavy noise contamination
                    - Score 1: Mostly unusable - critical info missing or buried in noise
                
                 Then you have to write the reason why you assigned that specific score.

                 Your answer must be ONLY a valid JSON formatted exactly like this:
                 {{  
                    "model_name" : "{SELECTED_MODEL}", 
                     "judge_score": 0,
                     "judge_feedback": "write your detailed explanation here"
                 }}"""
    
    payload = {
        "model": SELECTED_MODEL,
        "prompt": prompt,
        "format": "json",
        "stream": False
    }

    giudizio = None
    async with _ollama_lock:
        async with httpx.AsyncClient(timeout=180.0) as client:
            last_error = None
            for attempt in range(MAX_ATTEMPTS):
                try:
                    r = await client.post(URL, json=payload)
                    r.raise_for_status()
                    json_resp = r.json()
                    giudizio = json.loads(json_resp["response"])
                    break
                except Exception as e:
                    last_error = e
                    if attempt < MAX_ATTEMPTS - 1:
                        await asyncio.sleep(2)
                        continue

            if giudizio is None:
                giudizio = {
                    "model_name": SELECTED_MODEL,
                    "judge_score": 1,
                    "judge_feedback": f"{type(last_error).__name__}: {str(last_error) or repr(last_error.args)}"
                }

    return giudizio


async def extract_triples(text: str, titolo_ufficiale: str) -> dict:
    # --- 0. PULIZIA DEL TITOLO ---
    # Puliamo il titolo da eventuali scorie SEO prima ancora di iniziare
    if titolo_ufficiale:
        titolo_ufficiale = re.sub(r'\s*-\s*Film\s*\(\d{4}\).*$', '', titolo_ufficiale, flags=re.IGNORECASE)
        titolo_ufficiale = re.sub(r'\s*-\s*MYmovies\.it.*$', '', titolo_ufficiale, flags=re.IGNORECASE)
        titolo_ufficiale = re.sub(r'\s*-\s*IMDb.*$', '', titolo_ufficiale, flags=re.IGNORECASE)
        titolo_ufficiale = titolo_ufficiale.strip()
    # ---------------------------------------

    testo_pulito = text.strip()
    
    # 1. SMART CHUNKING (Context Injection)
    intestazione = testo_pulito[:200] if len(testo_pulito) >= 200 else testo_pulito
    
    chunks = []
    if len(testo_pulito) > 1500:
        split_idx = testo_pulito.rfind(' ', 0, 1500)
        chunks.append(testo_pulito[:split_idx])
        
        secondo_chunk = f"[Riferimento Film: {intestazione}]\n\n... CONTINUA ...\n{testo_pulito[split_idx:3000]}"
        chunks.append(secondo_chunk)
    else:
        chunks.append(testo_pulito)

    tutte_le_triple = []

    async def analizza_chunk(porzione_testo):
        prompt = f"""Sei un estrattore di dati per un Knowledge Graph. 
                    TITOLO UFFICIALE DEL FILM: "{titolo_ufficiale}"
                    Devi usare ESATTAMENTE questo nome in italiano per riferirti al film principale. 
                    NON usare traduzioni inglesi (es. The Dark Knight), NON usare varianti, e NON aggiungere mai simboli come "#".

                    REGOLE ONTOLOGIA (RISPETTA LA DIREZIONE), è VIETATO creare relazioni non specificate e avere soggetti/oggetti fuori dai tipi consentiti:
                    - Usa SOLO questi tipi: Person, Movie, Award, Genre
                    - RELAZIONE: DIRECTED -> (Soggetto: Person, Oggetto: Movie)
                    - RELAZIONE: ACTED_IN -> (Soggetto: Person, Oggetto: Movie)
                    - RELAZIONE: WON      -> (Soggetto: Movie o Person, Oggetto: Award)
                    - RELAZIONE: HAS_GENRE -> (Soggetto: Movie, Oggetto: Genre)

                    REGOLE OBBIGATORIE: 
                    1. I campi "subject" e "object" devono contenere SOLO il nome dell'entità. 
                    2. NON inserire MAI tag o classi nel nome (es. scrivi "Christopher Nolan", NON "[Person] Christopher Nolan"). 
                    3. NON estrarre MAI le parole "Curiosità", "Premi", "Awards", "Trivia", "Cast", "Troupe", "Biografia", "Opere Principali" come se fossero film. Sono titoli di sezione e vanno ignorati.
                    4. Una persona NON PUÒ mai agire in un film che ha il suo stesso identico nome (es. Cillian Murphy non recita nel film "Cillian Murphy"). Scarta queste triple.
                    5. Trascrivi i nomi dei film ESATTAMENTE come appaiono nel testo fornito (in italiano se sono scritti in italiano). NON tradurli in inglese.
                    6. DIVIETO DI ALLUCINAZIONE: Non usare MAI le tue conoscenze pregresse. Se un attore o un regista non è scritto ESPLICITAMENTE e CHIARAMENTE nel testo qui sotto, NON CREARE la tripla.
                    7. Attendoi allo spelling corretto dei nomi delle persone e dei film. Se il testo contiene errori di battitura, correggili.
                    TESTO:
                    {porzione_testo}

                    ESEMPIO JSON:
                    {{
                    "triples": [
                        {{"subject": "Quentin Tarantino", "subject_type": "Person", "relation": "DIRECTED", "object": "{titolo_ufficiale}", "object_type": "Movie"}},
                        {{"subject": "{titolo_ufficiale}", "subject_type": "Movie", "relation": "WON", "object": "Oscar", "object_type": "Award"}}
                    ]
                    }}
                    """
        
        payload = {
            "model": SELECTED_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.0,
                "num_ctx": 4096,
                "num_predict": 700,
                "stop": ["```\n", "<|im_end|>", "<|endoftext|>"]
            }
        }
        
        async with httpx.AsyncClient(timeout=300.0) as client:
            try:
                r = await client.post(URL, json=payload)
                r.raise_for_status()
                raw_response = r.json().get("response", "")
                
                match = re.search(r'\{.*\}', raw_response, re.DOTALL)
                if match:
                    dati_json = json.loads(match.group(0))
                    return dati_json.get("triples", dati_json.get("triple", dati_json.get("dati", [])))
                return []
            except Exception as e:
                print(f"Errore chunk: {e}", flush=True)
                return []

    # Esecuzione e Filtro
    async with _ollama_lock:
        for i, blocco in enumerate(chunks):
            triple_estratte = await analizza_chunk(blocco)
            
            # 1. Rimuoviamo TV_Serie dai tipi validi
            tipi_ok = {"Person", "Movie", "Award", "Genre"}
            rel_ok = {"DIRECTED", "ACTED_IN", "INTERPRETED", "HAS_GENRE", "WON"}

            for t in triple_estratte:
                # Estraiamo per sicurezza le variabili prima del controllo Blacklist per evitare ReferenceError
                sub = str(t.get("subject", ""))
                s_type = str(t.get("subject_type", "")).strip().capitalize()
                rel = str(t.get("relation", "")).strip().upper()
                obj = str(t.get("object", ""))
                o_type = str(t.get("object_type", "")).strip().capitalize()
                
                # --- INIZIO PULIZIA STRINGHE ---
                sub = re.sub(r'\[.*?\]\s*', '', sub).replace('#', '').strip()
                obj = re.sub(r'\[.*?\]\s*', '', obj).replace('#', '').strip()
                
                if s_type != "Movie":
                    sub = re.sub(r'^\d+\s+', '', sub).strip()
                if o_type != "Movie":
                    obj = re.sub(r'^\d+\s+', '', obj).strip()
                    
                # Applichiamo la NUOVA funzione regex per le date in base al tipo dichiarato dal modello    
                if s_type == "Movie":
                    sub = pulisci_date_titoli(sub)
                if o_type == "Movie":
                    obj = pulisci_date_titoli(obj)
                # --- FINE PULIZIA STRINGHE ---
                
                # --- NUOVO: NORMALIZZAZIONE AVANZATA (Punteggiatura + Typos) ---
                def semplifica(testo):
                    return re.sub(r'[^a-zA-Z0-9]', '', str(testo)).lower()
                
                titolo_base = semplifica(titolo_ufficiale)
                sub_base = semplifica(sub)
                obj_base = semplifica(obj)

                def is_similar(str1, str2):
                    if str1 in str2 or str2 in str1: 
                        return True
                    return difflib.SequenceMatcher(None, str1, str2).ratio() > 0.80

                # 2. Il Fuzzy Matching ora guarda solo i "Movie"
                if s_type == "Movie":
                    if len(sub_base) > 3 and is_similar(sub_base, titolo_base):
                        sub = titolo_ufficiale
                        
                if o_type == "Movie":
                    if len(obj_base) > 3 and is_similar(obj_base, titolo_base):
                        obj = titolo_ufficiale
                # -----------------------------------------------------
                
                blacklist = ["curiosità", "premi", "awards", "trivia", "cast", "troupe", "biografia"]
                
                # FILTRO 1: Salta se l'oggetto è nella blacklist
                if obj and obj.lower() in blacklist:
                    continue  
                # FILTRO 2: Salta l'autoreferenzialità
                if sub == obj:
                    continue

                if s_type in tipi_ok and o_type in tipi_ok and rel in rel_ok:
                    
                    # Auto-correttore per le direzioni ACTED_IN
                    if rel == "ACTED_IN" and s_type == "Movie" and o_type == "Person":
                        s_type, o_type = o_type, s_type
                        sub, obj = obj, sub
                        print(f"[CORRETTO] Direzione invertita per {sub} -> {obj}", flush=True)
                        
                    # Auto-correttore per le direzioni DIRECTED
                    if rel == "DIRECTED" and s_type == "Movie" and o_type == "Person":
                        s_type, o_type = o_type, s_type
                        sub, obj = obj, sub
                    
                    tutte_le_triple.append({
                        "subject": sub,
                        "subject_type": s_type,
                        "relation": rel,
                        "object": obj,
                        "object_type": o_type
                    })

    return {"triples": tutte_le_triple}



async def generate_cypher(question: str) -> str:
    prompt = f"""You are a Neo4j Cypher expert. Your task is to translate the user's Italian question into a working Cypher query.

GRAPH SCHEMA:
Nodes: Person, Movie, Award, Genre
Relationships:
(Person)-[:ACTED_IN]->(Movie)
(Person)-[:DIRECTED]->(Movie)
(Movie)-[:HAS_GENRE]->(Genre)
(Person)-[:WON]->(Award)
(Movie)-[:WON]->(Award)

STRICT RULES:
1. NEVER use exact string matching like {{name: "..."}}.
2. ALWAYS use "WHERE toLower(n.name) CONTAINS '...'" to search for nodes. Convert the search string to lowercase.
3. NEVER TRANSLATE proper names or movie titles into Italian. If the user asks about "The Prestige", the query must use CONTAINS "the prestige" (NOT "il prestigio" or "the prestigio"). Keep English titles in English.
4. Pay attention to variables: use Person (e.g., p.name) when searching for actors/directors, and Movie (e.g., m.name) when searching for movies.
5. Output ONLY the Cypher code. No explanations.

EXAMPLE 1 (Single entity):
Question: In che film ha recitato Leonardo DiCaprio?
Cypher Output: MATCH (p:Person)-[:ACTED_IN]->(m:Movie) WHERE toLower(p.name) CONTAINS "leonardo dicaprio" RETURN m.name AS Film LIMIT 15

EXAMPLE 2 (Two entities):
Question: Quali film diretti da Quentin Tarantino hanno Brad Pitt nel cast?
Cypher Output: MATCH (a:Person)-[:ACTED_IN]->(m:Movie)<-[:DIRECTED]-(d:Person) WHERE toLower(a.name) CONTAINS "brad pitt" AND toLower(d.name) CONTAINS "quentin tarantino" RETURN m.name AS Titolo_Film LIMIT 15

EXAMPLE 3:
Question: Quali attori hanno recitato in Batman Begins?
Cypher Output: MATCH (p:Person)-[:ACTED_IN]->(m:Movie) WHERE toLower(m.name) CONTAINS "batman begins" RETURN p.name AS Attore LIMIT 15

Question of the user: {question}
Output Cypher:"""

    payload = {
        "model": MODEL_CYPHER ,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.0} # Temperatura 0 per avere sintassi rigida
    }
    
    async with _ollama_lock:
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                r = await client.post(URL, json=payload)
                r.raise_for_status()
                cypher = r.json().get("response", "").strip()
                # Pulizia di sicurezza nel caso il LLM usi markdown (es. ```cypher ... ```)
                cypher = re.sub(r"^```cypher\s*", "", cypher, flags=re.IGNORECASE)
                cypher = re.sub(r"```$", "", cypher).strip()
                return cypher
            except Exception as e:
                print(f"Errore Text-to-Cypher: {e}")
                return ""

async def generate_rag_answer(question: str, db_data: list) -> str:
    if not db_data:
        return "Mi dispiace, ma non ho trovato informazioni a riguardo nel Knowledge Graph."

    valori = []
    for riga in db_data:
        valori.append(", ".join([str(v) for v in riga.values()]))
    
    elenco_testo = "\n".join([f"- {v}" for v in valori])

    # Prompt esplicito: spieghiamo al LLM che la lista È la risposta.
    prompt = f"""Sei un assistente virtuale. Il tuo UNICO compito è formulare una risposta discorsiva utilizzando i risultati forniti nei "DATI DAL DATABASE".
            È SEVERAMENTE VIETATO fare premesse, menzionare regole o spiegare il tuo ragionamento. Scrivi DIRETTAMENTE E SOLO la frase finale.
            DOMANDA DELL'UTENTE: {question}

            DATI DAL DATABASE (contenendi le risposte):{elenco_testo}
            
            REGOLE TASSATIVE:
            1. Se i dati dicono "NESSUN DATO PRESENTE", rispondi: "Mi dispiace, non ho trovato informazioni nel grafo."
            2. Se i dati contengono una lista di elementi (es. "- Cillian Murphy"), DEVI OBBLIGATORIAMENTE formulare una frase in italiano che includa TUTTI i risultati. È SEVERAMENTE VIETATO dire che non hai informazioni.
            3. Non aggiungere mai informazioni che non sono presenti nei dati forniti.
            4. La risposta deve contenere tutte le informazioni presenti nei dati, senza tralasciare nulla.

            ESEMPIO DI COMPORTAMENTO CORRETTO:
            Domanda: Quali attori hanno recitato nel film Batman Begins?
            Dati dal database: "Attore": "Cillian Murphy"
    
            Risposta: Nel film Batman Begins ha recitato Cillian Murphy."""

    payload = {
        "model": MODEL_CYPHER,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.0} 
    }
    
    async with _ollama_lock:
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                r = await client.post(URL, json=payload)
                r.raise_for_status()
                answer = r.json().get("response", "").strip()
                
                # --- LA GHIGLIOTTINA PYTHON (FALLBACK) ---
                parole_negazione = ["dispiace", "non ho trovato", "non sono riuscito", "non c'è", "non sia associato"]
                if any(parola in answer.lower() for parola in parole_negazione):
                    print("[FALLBACK ATTIVATO] Forzatura in corso.", flush=True)
                    return f"Secondo i dati estratti dal Knowledge Graph:\n{elenco_testo}"
                # -----------------------------------------
                
                return answer
            except Exception as e:
                print(f"Errore Text-to-Text: {e}", flush=True)
                return f"Ho trovato questi dati nel Knowledge Graph:\n{elenco_testo}"