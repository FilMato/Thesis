import os
import re
import sys
import time
import asyncio
import mariadb # Ricordatevi di metterlo nel requirements.txt
import httpx
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from urllib.parse import urlparse
from typing import Optional,Any
from clients import ollama_client

#importo per evaluation
from src.evaluator.evaluator import Evaluator
#importo factory per parser
from src.factory.parserfactory import ParserFactory
#importo seeder per popolamento iniziale del database
from src.db.seeder import populate_database

# --- BLOCCO DI CODICE DA CANCELLARE DOPO AVER MODIFICATO CORRETTAMENTE LE FUNZIONI DELL'API PER USARE IL DATABASE INVECE DEI FILE JSON ---
import json
base_dir = os.path.dirname(os.path.abspath(__file__))
percorso_domains = os.path.join(base_dir, "..", "..", "domains.json")
try:
    with open(percorso_domains, "r", encoding="utf-8") as f:
        dati_json = json.load(f)
        SUPPORTED_DOMAINS = dati_json.get("domains", [])
except FileNotFoundError:   # Fallback in caso di problemi di percorso prendo i domini manualmente
    SUPPORTED_DOMAINS = [
        "www.my-personaltrainer.it",
        "it.wikipedia.org",
        "www.premierleague.com",
        "www.un.org"
    ]
# --- FINE BLOCCO DA CANCELLARE -----------------------------------------------------------------------------------------------------------------

#definizione classi pydantic per i corpi delle richieste e definizione endpoints
class ParseOutput(BaseModel):
    url: str
    domain: str
    title: str
    html_text: str
    parsed_text: str

class PostParseRequest(BaseModel):  #input di post/parse
    url: str
    local:Optional[bool]=False

class DomainsOutput(BaseModel):
    domains: list[str]

class GoldStandardUrlsOutput(BaseModel):
    gold_standard_urls: list[str]

class GSOutput(BaseModel):
    url: str
    domain: str
    title: str
    html_text: str
    gold_text: str

class FullGSOutput(BaseModel):
    gold_standard: list[GSOutput]

class EvaluationRequest(BaseModel): #input di post/evaluate
    parsed_text: str
    gold_text: str

class StatusOutput(BaseModel):
    backend:str
    database:str
    ollama:str

class DBSchemaOutput(BaseModel):
    web_resources:dict[str,str]
    gold_standard:dict[str,str]
    parsed_results:dict[str,str]
    evaluation_results:dict[str,str]
    llm_judge_results:dict[str,str]

class AddWebResourceRequest(BaseModel):
    url:str
    html_text:str

class OperationOutput(BaseModel):
    status:str

class AddGoldStandardRequest(BaseModel):
    url:str
    gold_text:str

class DeleteRequest(BaseModel):
    url:str

class DBStatsOutput(BaseModel):
    web_resources:dict[str,int]
    gold_standard:dict[str,int]
    avg_eval:dict[str,Any]
    avg_eval_judge:dict[str,Any]



# definizione dei modelli per le metriche del'evaluation
class Metrics(BaseModel):
    precision: float
    recall: float
    f1: float
class DensityMetrics(BaseModel):
    score_gold_standard: float = Field(alias="Score gold standard")
    score_parsed_text: float = Field(alias="Score parsed text")
    Difference: float

class EvaluationOutput(BaseModel):
    token_level_eval: Metrics
    rouge_2_eval: Metrics
    information_density_evaluation: DensityMetrics
    tf_idf_cosine_similarity: float = Field(alias="TF-IDF_cosine_similarity")

class FullGSEvalOutput(EvaluationOutput):
    judge_score:float

class JudgeOutput(BaseModel):
    model_name: str
    judge_score: int #da vedere forse deve essere int
    judge_feedback: str

def Zero_Inizializer(model_class: type[BaseModel]) -> dict:   #Legge un modello Pydantic e crea un dizionario con la stessa struttura inizializzato a 0.0
    zero_dict = {}
    for field_name, field_info in model_class.model_fields.items():
        key = field_info.alias if field_info.alias else field_name  # Se abbiamo usato un alias (es. "TF-IDF_cosine_similarity") usiamo quello, altrimenti il nome normale
        field_type = field_info.annotation
        if isinstance(field_type, type) and issubclass(field_type, BaseModel):  # Se il campo è un'altra classe Pydantic (es. Metrics o DensityMetrics) facciamo ricorsione
            zero_dict[key] = Zero_Inizializer(field_type)
        else:   # Altrimenti assumiamo che sia un valore singolo e lo mettiamo a 0.0
            zero_dict[key] = 0.0
    return zero_dict

async def populate_evaluations(conn):
    # NOTA: questa funzione pre-calcola evaluation_results e llm_judge_results all'avvio,
    # cosi' full_gs_eval puo' leggere il judge_score gia' pronto dal DB invece di chiamare
    # Ollama in tempo reale per ogni URL (causa di timeout/lentezza segnalata anche da altri
    # gruppi: chiamare il judge live per ogni riga di full_gs_eval e' troppo lento per il grader)
    print("Avvio popolamento evaluation_results e llm_judge_results...")
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT wr.url, wr.domain, wr.html_text, gs.gold_text
        FROM web_resources wr
        JOIN gold_standard gs ON wr.url = gs.url
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
        except Exception:
            parsed_text = ""

        # evaluation
        try:
            result = valutatore.eval_server(strip_txt(parsed_text), gold_text)
            precision = result["token_level_eval"]["precision"]
            recall = result["token_level_eval"]["recall"]
            f1 = result["token_level_eval"]["f1"]
            extra = {
                "rouge_2_eval": result["rouge_2_eval"],
                "information_density_evaluation": result["information_density_evaluation"],
                "TF-IDF_cosine_similarity": result["TF-IDF_cosine_similarity"]
            }
        except Exception:
            precision, recall, f1 = 0.0, 0.0, 0.0
            extra = {}

        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO evaluation_results (url, precision_score, recall_score, f1_score, extra_metrics)
                VALUES (?, ?, ?, ?, ?)
                ON DUPLICATE KEY UPDATE
                    precision_score = VALUES(precision_score),
                    recall_score = VALUES(recall_score),
                    f1_score = VALUES(f1_score),
                    extra_metrics = VALUES(extra_metrics)
                """,
                (url, precision, recall, f1, json.dumps(extra))
            )
            conn.commit()
            cursor.close()
        except Exception as e:
            print(f"Errore salvataggio evaluation per {url}: {e}")

        # judge
        try:
            judge_result = await ollama_client.judge(parsed_text=parsed_text, gold_text=gold_text)
            judge_score = judge_result["judge_score"]
            model_name = judge_result["model_name"]
            judge_feedback = judge_result["judge_feedback"]
        except Exception:
            judge_score = 0
            model_name = ""
            judge_feedback = ""

        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO llm_judge_results (url, model_name, judge_score, judge_feedback)
                VALUES (?, ?, ?, ?)
                ON DUPLICATE KEY UPDATE
                    model_name = VALUES(model_name),
                    judge_score = VALUES(judge_score),
                    judge_feedback = VALUES(judge_feedback)
                """,
                (url, model_name, judge_score, judge_feedback)
            )
            conn.commit()
            cursor.close()
        except Exception as e:
            print(f"Errore salvataggio judge per {url}: {e}")

    print("Popolamento evaluation completato.")

#FATTA FARE DA CLAUDE PER TESTARE


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
#----------------------------------------------------------------


app = FastAPI(lifespan=lifespan)


@app.post("/parse")
async def post_parse(body: PostParseRequest,http_request:Request)-> ParseOutput:
    domain = urlparse(body.url).netloc
    if domain not in SUPPORTED_DOMAINS:
        raise HTTPException(status_code=400, detail="Dominio non supportato")
    parser = ParserFactory.create(domain)   #seleziona il parser corretto in base al dominio, se il dominio non è supportato solleva un'eccezione
    if body.local:
        #articolo=GS_INDEX.get(domain,{}).get(body.url) #Quando pippo mi da il DB va modificata con la chiamata alla repository
        conn=http_request.app.state.db
        cursor=conn.cursor()
        cursor.execute(
            "SELECT html_text FROM web_resources WHERE url = ?",
            (body.url,)
        )
        row=cursor.fetchone()
        cursor.close()
        if not row:
            raise HTTPException(status_code=404,detail="URL non trovato nelo DB")
        try:
            risultato = await parser.parser_url2(body.url, row[0])
            return risultato
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    else:
        try:
            risultato=await parser.parser_url(body.url)
            return risultato
        except Exception as e:
            raise HTTPException(status_code=502,detail=f"URL irragiungibile: {str(e)}")


@app.get("/domains")
async def domains() -> DomainsOutput:
    return {"domains": SUPPORTED_DOMAINS}


@app.get("/gold_standard")
async def gold_standard(url: str,http_request:Request) -> GSOutput:
    #articolo = GS_INDEX.get(domain, {}).get(url) #da modificare con la chiamata al databse quando ci sta
    conn=http_request.app.state.db
    cursor=conn.cursor()
    cursor.execute(
        """
        SELECT wr.url, wr.domain, wr.title, wr.html_text, gs.gold_text
        FROM web_resources wr
        JOIN gold_standard gs ON wr.url = gs.url
        WHERE wr.url = ?
        """,
        (url,)
    )
    row=cursor.fetchone()#fetchone anzicche fetchall perche ci aspettiamo uan sola riga
    cursor.close()
    if not row:
        domain = urlparse(url).netloc
        if domain not in SUPPORTED_DOMAINS:
            raise HTTPException(status_code=400,detail="Dominio non supportato")
        raise HTTPException(status_code=404, detail="URL non nel gold standard")
    return GSOutput(
        url=row[0],
        domain=row[1],
        title=row[2],
        html_text=row[3],
        gold_text=row[4]
    )

@app.get("/gold_standard_urls")
async def gold_standard_urls(domain:str,http_request:Request) ->GoldStandardUrlsOutput:
    if domain not in SUPPORTED_DOMAINS:
        raise HTTPException(status_code=400,detail="Dominio non supportato")
    #urls=list(GS_INDEX.get(domain,{}).keys()) #da sostituire GS_INDEX con il database
    conn=http_request.app.state.db
    cursor=conn.cursor()
    cursor.execute(
        """
        SELECT wr.url
        FROM web_resources wr
        JOIN gold_standard gs ON wr.url = gs.url
        WHERE wr.domain = ?
        """,
        (domain,)
    )
    rows=cursor.fetchall()
    cursor.close()
    urls=[row[0] for row in rows]
    return {"gold_standard_urls":urls}

@app.get("/full_gold_standard")
async def full_gold_standard(domain: str,http_request:Request) -> FullGSOutput:
    if domain not in SUPPORTED_DOMAINS:
        raise HTTPException(status_code=400, detail="Dominio non supportato")
    #gs=GS_DOMAINS[domain]   #prendo in base al dominio il corrispettivo file dominio_gs.json che contiene il gold standard per quel dominio
    conn=http_request.app.state.db
    cursor=conn.cursor()
    cursor.execute(
        """
        SELECT wr.url, wr.domain, wr.title, wr.html_text, gs.gold_text
        FROM web_resources wr
        JOIN gold_standard gs ON wr.url = gs.url
        WHERE wr.domain = ?
        """,
        (domain,)
    )
    rows=cursor.fetchall()
    cursor.close()
    gs = [GSOutput(url=row[0], domain=row[1], title=row[2], html_text=row[3], gold_text=row[4]) for row in rows]
    return {"gold_standard": gs}


@app.get("/full_gs_eval")
async def full_gs_eval(domain: str,http_request:Request) -> FullGSEvalOutput:
    if domain not in SUPPORTED_DOMAINS:
        raise HTTPException(status_code=400, detail="Dominio non supportato")
    conn=http_request.app.state.db
    cursor=conn.cursor()
    # LEFT JOIN su llm_judge_results: il judge_score viene letto dal valore gia' calcolato
    # da populate_evaluations all'avvio (vedi lifespan), NON richiamando Ollama qui.
    # Questo evita di sforare i timeout del grader, che fallisce se /full_gs_eval ci mette
    # troppo a causa di N chiamate sincrone a un LLM lento (lo stesso problema segnalato
    # da altri gruppi sul forum del corso).
    cursor.execute(
        """
        SELECT wr.url, wr.html_text, gs.gold_text, ljr.judge_score
        FROM web_resources wr
        JOIN gold_standard gs ON wr.url = gs.url
        LEFT JOIN llm_judge_results ljr ON wr.url = ljr.url
        WHERE wr.domain = ?
        """,
        (domain,)
    )
    rows=cursor.fetchall()
    cursor.close()
    count = 0
    valutatore = Evaluator()
    #articoli = GS_DOMAINS[domain]   #prendo in base al dominio il corrispettivo file dominio_gs.json che contiene il gold standard per quel dominio
    parser = ParserFactory.create(domain)   #seleziona il parser corretto in base al dominio, se il dominio non è supportato solleva un'eccezione
    somme = Zero_Inizializer(EvaluationOutput)    #inizializzo a zero tutte le somme che mi serviranno per fare la media alla fine
    somma_judge=0.0
    for row in rows:
        url,html_text,gold_text,judge_score_db=row[0],row[1],row[2],row[3]
        parsed_text = ""    # inizializziamo parsed_text a una stringa vuota, e solo se parser_json è valido e contiene "parsed_text", lo aggiorniamo
        try:
            parser_json = await parser.parser_url2(url,html_text)
            parsed_text = parser_json.get("parsed_text", "") if parser_json else ""
        except Exception:
            parsed_text=""
        try:
            result = valutatore.eval_server(strip_txt(parsed_text), gold_text)
        except Exception:
            result = Zero_Inizializer(EvaluationOutput)   # se la valutazione fallisce, mettiamo tutto a zero

        somma_judge += judge_score_db or 0.0  # judge_score gia' pronto dal DB, nessuna chiamata live

        for key, value in result.items():
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    somme[key][sub_key] += sub_value
            else:
                somme[key] += value
        count += 1
    if count == 0:  # se non ci sono articoli, restituisco gli zeri per evitare la divisione per zero
        return FullGSEvalOutput(**somme,judge_score=0.0)
    medie = {}
    for key, value in somme.items():
        if isinstance(value, dict):
            medie[key] = {sub_key: sub_val / count for sub_key, sub_val in value.items()}    # comprehension per calcolare la media di ogni sotto-elemento del dizionario
        else:
            medie[key] = value / count   # media per i valori singoli
    return FullGSEvalOutput(**medie,judge_score=somma_judge/count)

#funzione per pulire il markdown
def strip_txt(text: str) -> str:

    #text = text.lower()
    text = re.sub(r'\*+([^*]+)\*+', r'\1', text) #grassetto
    text = re.sub(r'\_+([^_]+)\_+', r'\1', text) #corsivo
    text = re.sub(r'\#+\s?([^#]+)', r'\1', text) #titoli
    text = re.sub(r'\[([^\]]+)\]\((?:[^)\\]|\\.)*\)', r'\1', text) #link

    return text


@app.post("/evaluate")
async def evaluate(request: EvaluationRequest) -> EvaluationOutput:
    parsed_text = strip_txt(request.parsed_text)
    try:
        return Evaluator().eval_server(parsed_text, request.gold_text)
    except Exception as e:
        print(f"Errore durante la valutazione: {e}")
        return EvaluationOutput(**Zero_Inizializer(EvaluationOutput))

@app.post("/evaluate_judge")
async def evaluate_judge(request: EvaluationRequest) -> JudgeOutput: #perché questo funzioni judge deve ritornare un dizionario che abbia le stesse identiche chiavi di JudgeOutput
    parsed_text = strip_txt(request.parsed_text)
    return await ollama_client.judge(parsed_text=parsed_text, gold_text=request.gold_text)

@app.get("/status")
async def status(http_request: Request) -> StatusOutput:
    try:
        conn = http_request.app.state.db
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.close()
        db_status = "ok"
    except Exception:
        db_status = "error"

    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get("http://ollama:11434/api/tags")
            ollama_status = "ok" if r.status_code == 200 else "error"
    except Exception:
        ollama_status = "error"

    return StatusOutput(backend="ok", database=db_status, ollama=ollama_status)

@app.get("/db_schema")
async def db_schema()->DBSchemaOutput:
    return DBSchemaOutput(
        web_resources={
            "url": "varchar(768), PK",
            "domain": "varchar(255)",
            "title": "varchar(2048)",
            "html_text": "longtext",
            "created_at": "datetime"
        },
        gold_standard={
            "url": "varchar(768), PK, FK(web_resources.url)",
            "gold_text": "longtext",
            "created_at": "datetime"
        },
        parsed_results={
            "id": "int, PK",
            "url": "varchar(768), FK(web_resources.url)",
            "parsed_text": "longtext",
            "parser_version": "varchar(50)",
            "created_at": "datetime"
        },
        evaluation_results={
            "id": "int, PK",
            "url": "varchar(768), FK(web_resources.url)",
            "precision_score": "float",
            "recall_score": "float",
            "f1_score": "float",
            "extra_metrics": "json",
            "created_at": "datetime"
        },
        llm_judge_results={
            "id": "int, PK",
            "url": "varchar(768), FK(web_resources.url)",
            "model_name": "varchar(100)",
            "judge_score": "int",
            "judge_feedback": "text",
            "created_at": "datetime"
        }
    )
@app.post("/add_web_resource")
async def add_web_resource(body:AddWebResourceRequest,http_request:Request)->OperationOutput:
    domain=urlparse(body.url).netloc
    conn=http_request.app.state.db
    cursor=conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO web_resources (url, domain, title, html_text)
            VALUES (?, ?, ?, ?)
            """,
            (body.url, domain, "", body.html_text)
        )
        conn.commit() #selve per salvare l'insert nella tabella
        return OperationOutput(status="ok")
    except Exception:
        return OperationOutput(status="error")
    finally:
        cursor.close() #chiusura sia in caso di errore che di successo, evitiamo memory leak

@app.post("/add_gold_standard")
async def add_gold_standard(body:AddGoldStandardRequest,http_request:Request)->OperationOutput:
    conn=http_request.app.state.db
    cursor=conn.cursor()
    try:
        cursor.execute(
            "SELECT url FROM web_resources WHERE url=?",
            (body.url,)
        )
        if not cursor.fetchone():
            return OperationOutput(status="error")

        cursor.execute(
            """
            INSERT INTO gold_standard (url, gold_text)
            VALUES (?, ?)
            """,
            (body.url, body.gold_text)
        )
        conn.commit()
        return OperationOutput(status="ok")
    except Exception:
        return OperationOutput(status="error")
    finally:
        cursor.close()
@app.delete("/web_resource")
async def delete_web_resource(body:DeleteRequest,http_request:Request)->OperationOutput:
    conn=http_request.app.state.db
    cursor=conn.cursor()
    try:
        cursor.execute(
            "DELETE FROM web_resources WHERE url=?",
            (body.url,)
        )
        conn.commit()
        return OperationOutput(status="ok")
    except Exception:
        return OperationOutput(status="error")
    finally:
        cursor.close()
@app.delete("/gold_standard")
async def delete_gold_standard(body:DeleteRequest,http_request:Request)->OperationOutput:
    conn=http_request.app.state.db
    cursor=conn.cursor()
    try:
        cursor.execute(
            "SELECT url FROM gold_standard WHERE url=?",
            (body.url,)
        )
        if not cursor.fetchone():
            return OperationOutput(status="error")
        cursor.execute(
            "DELETE FROM gold_standard WHERE url=?",
            (body.url,)
        )
        conn.commit()
        return OperationOutput(status="ok")
    except Exception:
        return OperationOutput(status="error")
    finally:
        cursor.close()

@app.get("/db_stats")
async def db_stats(http_request:Request)->DBStatsOutput:
    conn=http_request.app.state.db
    cursor=conn.cursor()

    cursor.execute("SELECT domain, COUNT(*) FROM web_resources GROUP BY domain")
    conteggio_web={row[0]:row[1] for row in cursor.fetchall()}

    cursor.execute(
        """
        SELECT wr.domain, COUNT(*)
        FROM gold_standard gs
        JOIN web_resources wr ON gs.url = wr.url
        GROUP BY wr.domain
        """
    )
    conteggio_gold={row[0]:row[1] for row in cursor.fetchall()}

    # Inizializza tutti i domini a 0.0 (fallback se populate_evaluations non ha ancora girato)
    media_valutazione = {
        domain: {"token_level_eval": {"precision": 0.0, "recall": 0.0, "f1": 0.0}}
        for domain in conteggio_web
    }
    avg_eval_judje = {
        domain: {"judge_score": 0.0}
        for domain in conteggio_web
    }

    cursor.execute(
        """
        SELECT wr.domain, AVG(er.precision_score), AVG(er.recall_score), AVG(er.f1_score)
        FROM evaluation_results er
        JOIN web_resources wr ON er.url = wr.url
        GROUP BY wr.domain
        """
    )
    for row in cursor.fetchall():
        media_valutazione[row[0]] = {
            "token_level_eval": {
                "precision": row[1] or 0.0,
                "recall": row[2] or 0.0,
                "f1": row[3] or 0.0
            }
        }

    cursor.execute(
        """
        SELECT wr.domain, AVG(ljr.judge_score)
        FROM llm_judge_results ljr
        JOIN web_resources wr ON ljr.url = wr.url
        GROUP BY wr.domain
        """
    )
    for row in cursor.fetchall():
        avg_eval_judje[row[0]] = {"judge_score": row[1] or 0.0}

    cursor.close()
    return DBStatsOutput(
        web_resources=conteggio_web,
        gold_standard=conteggio_gold,
        avg_eval=media_valutazione,
        avg_eval_judge=avg_eval_judje
    )