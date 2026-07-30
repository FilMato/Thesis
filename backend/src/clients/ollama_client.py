import asyncio
import httpx
import json

URL = "http://ollama:11434/api/generate" #l'API di ollama si raggiunge di default da questo url e invece di localhost si mette il nome del servizio per far si che funzioni su docker
SELECTED_MODEL = "qwen2.5:3b" #il modello viene preliminarmente incasellato in una costante per aumentare l'alterabilità del codice
MAX_CHARS = 1000

# Ollama (con un solo modello caricato) gestisce le richieste in slot limitati: se
# populate_evaluations() (che ne lancia decine in sequenza all'avvio) e una chiamata
# "live" dell'utente arrivano in contemporanea, il server puo' rispondere 500 anche
# dopo aver generato correttamente il testo (contesa sullo slot/KV-cache). Questo lock
# serializza TUTTE le chiamate al judge nel processo backend, eliminando la concorrenza
# come causa del 500.
_ollama_lock = asyncio.Lock()
MAX_ATTEMPTS = 2  # 1 retry in caso di errore prima di usare il fallback

"""gestisce la comunicazione con l'API di ollama, si occupa di estrarre il json dalla risposta
del modello, in caso di output non parsabile applica il fallback 
(score = 1, feedback = "Il modello non ha rispettato il formato richiesto"), 
restituisce sempre 200 con il modello popolato, l'output è un dizionario pyhton"""

#note sul prompt: originariamente scritto in inglese , per evitare che il modello fosse troppo severo in presenza di testi lunghi con
#inevitabili imperfezioni si è deciso di dare priorità alla preservazione del contenuto dell'url (in quanto l'obiettivo è che questo vada in pasto ad un LLM)
#eventualmente è possibile aggiungere degli score "di mezzo" (e.g 4.5, 4.75..) per rendere la valutazione più precisa

#problemi: ora è molto lento (1 minuto e mezzo in media per formulare un giudizio), credo dipenda dal modello utilizzato
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
    # Il lock impedisce che questa chiamata sovrapponga ad un'altra chiamata al judge
    # gia' in corso (es. quella lanciata da populate_evaluations() all'avvio): cosi'
    # Ollama riceve sempre una sola richiesta di generazione alla volta.
    async with _ollama_lock:
        async with httpx.AsyncClient(timeout=180.0) as client:
            last_error = None
            for attempt in range(MAX_ATTEMPTS):
                try:
                    r = await client.post(URL, json=payload)
                    r.raise_for_status()
                    json_resp = r.json()
                    giudizio = json.loads(json_resp["response"])
                    break  # successo, niente retry
                except Exception as e:
                    last_error = e
                    if attempt < MAX_ATTEMPTS - 1:
                        await asyncio.sleep(2)  # piccola pausa prima del retry
                        continue

            if giudizio is None:  #logica di fallback nel caso ci fossero problemi, restituisce comunque un dizionario in modo tale
                #da non intaccare la performance totale del backend
                giudizio = {
                    "model_name": SELECTED_MODEL,
                    "judge_score": 1,
                    "judge_feedback": f"{type(last_error).__name__}: {str(last_error) or repr(last_error.args)}"
                }

    return giudizio



async def extract_triples(text: str) -> dict:
    """
    Estrae triple relazionali da un testo fornito utilizzando il modello LLM locale.
    Applica un'ontologia rigida per l'inserimento in Neo4j e restituisce un dizionario.
    """
    prompt = f"""Sei un estrattore avanzato di dati per un Knowledge Graph. 
Il tuo compito è leggere il seguente testo ed estrarre le relazioni logiche (triple) tra le entità in esso contenute.

TESTO DA ANALIZZARE:
{text[:MAX_CHARS]}

REGOLE RIGOROSE DELL'ONTOLOGIA:
1. Devi classificare il campo "subject_type" e "object_type" ESCLUSIVAMENTE con uno di questi valori ammessi:
   Person, Movie, TV_Serie, Character, Award, Genre

2. Devi classificare il campo "relation" ESCLUSIVAMENTE con uno di questi valori ammessi:
    DIRECTED tra Person e Movie o TV_Serie,
    ACTED_IN tra Person e Movie o TV_Serie, 
    INTERPRETED tra Person e Character, 
    APPEARS_IN tra Character e Movie o TV_Serie, 
    HAS_GENRE  tra Genre e Movie o TV_Serie, 
    WON tra Award e Movie o TV_Serie

3. La tua risposta deve essere UNICAMENTE un oggetto JSON valido contenente una lista chiamata "triples".
4. NON aggiungere spiegazioni, formattazioni markdown all'esterno del blocco JSON, o risposte discorsive.

ESEMPIO DI FORMATO RICHIESTO:
{{
    "triples": [
        {{
            "subject": "Christopher Nolan",
            "subject_type": "Person",
            "relation": "DIRECTED",
            "object": "Inception",
            "object_type": "Movie"
        }}
    ]
}}
"""
    
    payload = {
        "model": SELECTED_MODEL,
        "prompt": prompt,
        #"format": "json", 
        "stream": False,
        "options": {
            "temperature": 0.0
            }
        }

    risultato = None
    
    async with _ollama_lock:
        async with httpx.AsyncClient(timeout=500.0) as client:
            last_error = None
            for attempt in range(MAX_ATTEMPTS):
                try:
                    r = await client.post(URL, json=payload)
                    r.raise_for_status()
                    json_resp = r.json()
                    risultato = json.loads(json_resp["response"])
                    break
                except Exception as e:
                    last_error = e
                    if attempt < MAX_ATTEMPTS - 1:
                        await asyncio.sleep(2)
                        continue

            if risultato is None:
                risultato = {
                    "triples": [],
                    "error": f"{type(last_error).__name__}: {str(last_error) or repr(last_error.args)}"
                }

    return risultato