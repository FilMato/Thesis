from fastapi import APIRouter, HTTPException, Request
from urllib.parse import urlparse
from src.factory.parserfactory import ParserFactory
from src.evaluator.evaluator import Evaluator
from clients import ollama_client
from src.rest.structures import (
    PostParseRequest, ParseOutput, DomainsOutput, GoldStandardUrlsOutput, 
    GSOutput, FullGSOutput, FullGSEvalOutput, EvaluationRequest, 
    EvaluationOutput, JudgeOutput
)
from src.rest.utility import SUPPORTED_DOMAINS, Zero_Inizializer, strip_txt

router = APIRouter(tags=["Parsing & Evaluation"])

@router.post("/parse")
async def post_parse(body: PostParseRequest, http_request: Request) -> ParseOutput:
    domain = urlparse(body.url).netloc
    if domain not in SUPPORTED_DOMAINS:
        raise HTTPException(status_code=400, detail="Dominio non supportato")
    parser = ParserFactory.create(domain)    #seleziona il parser corretto in base al dominio, se il dominio non è supportato solleva un'eccezione
    if body.local:
        conn = http_request.app.state.db
        cursor = conn.cursor()
        cursor.execute("SELECT html_text FROM web_resources WHERE url = ?", (body.url,))
        row = cursor.fetchone()
        cursor.close()
        if not row:
            raise HTTPException(status_code=404, detail="URL non trovato nelo DB")
        try:
            risultato = await parser.parser_url2(body.url, row[0])
            return risultato
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    else:
        try:
            risultato = await parser.parser_url(body.url)
            return risultato
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"URL irragiungibile: {str(e)}")

@router.get("/domains")
async def domains() -> DomainsOutput:
    return {"domains": SUPPORTED_DOMAINS}

@router.get("/gold_standard")
async def gold_standard(url: str, http_request: Request) -> GSOutput:
    conn = http_request.app.state.db
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT wr.url, wr.domain, wr.title, wr.html_text, gs.gold_text
        FROM web_resources wr
        JOIN gold_standard gs ON wr.url = gs.url
        WHERE wr.url = ?
        """,
        (url,)
    )
    row = cursor.fetchone() #fetchone anzicche fetchall perche ci aspettiamo uan sola riga
    cursor.close()
    if not row:
        domain = urlparse(url).netloc
        if domain not in SUPPORTED_DOMAINS:
            raise HTTPException(status_code=400, detail="Dominio non supportato")
        raise HTTPException(status_code=404, detail="URL non nel gold standard")
    return GSOutput(url=row[0], domain=row[1], title=row[2], html_text=row[3], gold_text=row[4])

@router.get("/gold_standard_urls")
async def gold_standard_urls(domain: str, http_request: Request) -> GoldStandardUrlsOutput:
    if domain not in SUPPORTED_DOMAINS:
        raise HTTPException(status_code=400, detail="Dominio non supportato")
    conn = http_request.app.state.db
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT wr.url
        FROM web_resources wr
        JOIN gold_standard gs ON wr.url = gs.url
        WHERE wr.domain = ?
        """,
        (domain,)
    )
    rows = cursor.fetchall()
    cursor.close()
    urls = [row[0] for row in rows]
    return {"gold_standard_urls": urls}

@router.get("/full_gold_standard")
async def full_gold_standard(domain: str, http_request: Request) -> FullGSOutput:
    if domain not in SUPPORTED_DOMAINS:
        raise HTTPException(status_code=400, detail="Dominio non supportato")
    conn = http_request.app.state.db
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT wr.url, wr.domain, wr.title, wr.html_text, gs.gold_text
        FROM web_resources wr
        JOIN gold_standard gs ON wr.url = gs.url
        WHERE wr.domain = ?
        """,
        (domain,)
    )
    rows = cursor.fetchall()
    cursor.close()
    gs = [GSOutput(url=row[0], domain=row[1], title=row[2], html_text=row[3], gold_text=row[4]) for row in rows]
    return {"gold_standard": gs}

@router.get("/full_gs_eval")
async def full_gs_eval(domain: str, http_request: Request) -> FullGSEvalOutput:
    if domain not in SUPPORTED_DOMAINS:
        raise HTTPException(status_code=400, detail="Dominio non supportato")
    conn = http_request.app.state.db
    cursor = conn.cursor()
    
    # Lettura veloce dal database: non blocchiamo l'utente!
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
    rows = cursor.fetchall()
    cursor.close()
    count = 0
    valutatore = Evaluator()
    parser = ParserFactory.create(domain)   
    somme = Zero_Inizializer(EvaluationOutput)    
    somma_judge = 0.0
    for row in rows:
        url, html_text, gold_text, judge_score_db = row[0], row[1], row[2], row[3]
        parsed_text = ""    
        try:
            parser_json = await parser.parser_url2(url, html_text)
            parsed_text = parser_json.get("parsed_text", "") if parser_json else ""
        except Exception:
            parsed_text = ""
        try:
            result = valutatore.eval_server(strip_txt(parsed_text), gold_text)
        except Exception:
            result = Zero_Inizializer(EvaluationOutput)   

        somma_judge += judge_score_db or 0.0  # judge_score gia' pronto dal DB

        for key, value in result.items():
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    somme[key][sub_key] += sub_value
            else:
                somme[key] += value
        count += 1
    if count == 0:  
        return FullGSEvalOutput(**somme, judge_score=0.0)
    medie = {}
    for key, value in somme.items():
        if isinstance(value, dict):
            medie[key] = {sub_key: sub_val / count for sub_key, sub_val in value.items()}    
        else:
            medie[key] = value / count   
    return FullGSEvalOutput(**medie, judge_score=somma_judge/count)

@router.post("/evaluate")
async def evaluate(request: EvaluationRequest) -> EvaluationOutput:
    parsed_text = strip_txt(request.parsed_text)
    try:
        return Evaluator().eval_server(parsed_text, request.gold_text)
    except Exception as e:
        print(f"Errore durante la valutazione: {e}")
        return EvaluationOutput(**Zero_Inizializer(EvaluationOutput))

@router.post("/evaluate_judge")
async def evaluate_judge(request: EvaluationRequest) -> JudgeOutput: 
    parsed_text = strip_txt(request.parsed_text)
    return await ollama_client.judge(parsed_text=parsed_text, gold_text=request.gold_text)