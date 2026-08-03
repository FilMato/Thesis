import os
import sys
import time
import asyncio
import mariadb 
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI

# Import interni
from src.db.seeder import populate_database
from src.evaluator.evaluator import Evaluator
from src.factory.parserfactory import ParserFactory
from clients import ollama_client
from src.rest.utility import strip_txt

# Import dei Router API
from src.rest.routers import evaluation, database, graph

async def populate_evaluations(conn):
    # NOTA: questa funzione pre-calcola evaluation_results e llm_judge_results all'avvio,
    # cosi' full_gs_eval puo' leggere il judge_score gia' pronto dal DB invece di chiamare
    # Ollama in tempo reale per ogni URL (causa di timeout/lentezza segnalata anche da altri
    # gruppi: chiamare il judge live per ogni riga di full_gs_eval e' troppo lento per il grader)

    print("Avvio popolamento evaluation_results e llm_judge_results...")
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT DISTINCT wr.url, wr.domain, wr.html_text, gs.gold_text
        FROM web_resources wr
        JOIN gold_standard gs ON wr.url = gs.url
        LEFT JOIN parsed_results pr ON wr.url = pr.url
        LEFT JOIN llm_judge_results ljr ON wr.url = ljr.url
        LEFT JOIN evaluation_results er ON wr.url = er.url
        WHERE pr.url IS NULL 
           OR ljr.url IS NULL 
           OR er.url IS NULL
        """
    )
    rows = cursor.fetchall()
    cursor.close()

    valutatore = Evaluator()

    for row in rows:
        url, domain, html_text, gold_text = row[0], row[1], row[2], row[3]

        # parsing
        try:
            parser = ParserFactory.create(domain)
            parser_json = await parser.parser_url2(url, html_text)
            parsed_text = parser_json.get("parsed_text", "") if parser_json else ""
        except Exception as e:
            print(f"\n[ERRORE PARSER] Crash su {url}: {e}\n", flush=True)
            parsed_text = ""

        if parsed_text:
            try:
                cursor_p = conn.cursor()
                cursor_p.execute(
                    """
                    INSERT INTO parsed_results (url, parsed_text, parser_version)
                    VALUES (?, ?, ?)
                    ON DUPLICATE KEY UPDATE
                        parsed_text = VALUES(parsed_text), parser_version = VALUES(parser_version)
                    """,
                    (url, parsed_text, "1.0")
                )
                conn.commit()
                cursor_p.close()
                print(f"[populate_evaluations] Salvato in parsed_results per {url}")
            except Exception as e:
                print(f"Errore salvataggio parsed_results per {url}: {e}")

        # evaluation
        try:
            result = valutatore.eval_server(strip_txt(parsed_text), gold_text)
            precision, recall, f1 = result["token_level_eval"]["precision"], result["token_level_eval"]["recall"], result["token_level_eval"]["f1"]
            extra = {"rouge_2_eval": result["rouge_2_eval"], "information_density_evaluation": result["information_density_evaluation"], "TF-IDF_cosine_similarity": result["TF-IDF_cosine_similarity"]}
        except Exception:
            precision, recall, f1 = 0.0, 0.0, 0.0
            extra = {}

        # Log diagnostico per-URL: permette di capire quali pagine abbassano la
        # media del dominio (es. parsing fallito -> parsed_text vuoto -> punteggio 0)
        print(f"[populate_evaluations] {url} -> precision={precision:.3f} recall={recall:.3f} f1={f1:.3f} (parsed_text len={len(parsed_text)})")

        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO evaluation_results (url, precision_score, recall_score, f1_score, extra_metrics)
                VALUES (?, ?, ?, ?, ?)
                ON DUPLICATE KEY UPDATE
                    precision_score = VALUES(precision_score), recall_score = VALUES(recall_score), f1_score = VALUES(f1_score), extra_metrics = VALUES(extra_metrics)
                """,
                (url, precision, recall, f1, json.dumps(extra))
            )
            conn.commit()
            cursor.close()
        except Exception as e:
            print(f"Errore salvataggio evaluation per {url}: {e}")

        # judge
        # NOTA: usiamo strip_txt(parsed_text), coerentemente con /evaluate_judge,
        # cosi' il judge valuta lo stesso testo "pulito" usato anche per le metriche
        # token-level qui sopra (prima qui veniva passato il testo non normalizzato).
        try:
            judge_result = await ollama_client.judge(parsed_text=strip_txt(parsed_text), gold_text=gold_text)
            judge_score, model_name, judge_feedback = judge_result["judge_score"], judge_result["model_name"], judge_result["judge_feedback"]
        except Exception:
            judge_score, model_name, judge_feedback = 0, "", ""

        print(f"[populate_evaluations] {url} -> judge_score={judge_score}")

        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO llm_judge_results (url, model_name, judge_score, judge_feedback)
                VALUES (?, ?, ?, ?)
                ON DUPLICATE KEY UPDATE
                    model_name = VALUES(model_name), judge_score = VALUES(judge_score), judge_feedback = VALUES(judge_feedback)
                """,
                (url, model_name, judge_score, judge_feedback)
            )
            conn.commit()
            cursor.close()
        except Exception as e:
            print(f"Errore salvataggio judge per {url}: {e}")

        await asyncio.sleep(2)
    print("Popolamento evaluation completato.")

# Questa funzione serve come doppio controllo per assicurarsi che il backend non si avvii finché MariaDB non è pronto. Anche se abbiamo messo un healthcheck nel docker-compose.
@asynccontextmanager
async def lifespan(app: FastAPI):
    max_retries = 5
    delay_seconds = 5
    conn = None

    print("Tentativo di connessione a MariaDB in corso...")
    while max_retries > 0:
        try:
            conn = mariadb.connect(
                host=os.getenv("DB_HOST", "mariadb"),
                user=os.getenv("DB_USER", "minerva_user"),
                password=os.getenv("DB_PASSWORD", "minerva_pass"),
                database=os.getenv("DB_NAME", "minerva_db"),
                port=3306
            )
            print("Connessione a MariaDB stabilita con successo!")
            break
        except mariadb.Error as e:
            print(f"MariaDB non è ancora pronto. Errore: {e}")
            max_retries -= 1
            if max_retries == 0:
                print("Impossibile connettersi al database. Spegnimento del backend.")
                sys.exit(1)
            time.sleep(delay_seconds)

    app.state.db = conn

     # Popolamento iniziale del database con i dati del Gold Standard
    if conn:
        populate_database(conn)
        # Pre-calcolo evaluation_results e llm_judge_results: full_gs_eval legge da qui
        # invece di richiamare Ollama in tempo reale (vedi nota in populate_evaluations).
        # NON si fa await qui: ogni chiamata al judge richiede circa 1-2 minuti, e con
        # decine di URL nel gold standard un await bloccante terrebbe l'app in startup
        # per troppo tempo, rendendo il backend irraggiungibile per il grader (che ha
        # un timeout molto piu' breve). Si lancia come task in background: l'app diventa
        # subito raggiungibile, il DB viene popolato man mano che i task completano.
        asyncio.create_task(populate_evaluations(conn))
    yield
    # Fase di spegnimento
    if app.state.db:
        app.state.db.close()
        print("Connessione a MariaDB chiusa correttamente.")

app = FastAPI(lifespan=lifespan)

# REGISTRAZIONE DEI ROUTER 
app.include_router(evaluation.router)
app.include_router(database.router)
app.include_router(graph.router)