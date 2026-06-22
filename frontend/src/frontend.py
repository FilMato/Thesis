import os
import httpx
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
from urllib.parse import urlencode
import asyncio

app = FastAPI()

# URL del backend (sovrascrivibile via variabile d'ambiente per Docker)
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8003")

templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))


async def get_status() -> dict:
    """Recupera lo stato del sistema dal backend."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{BACKEND_URL}/status")
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass
    return {"backend": "error", "database": "error", "ollama": "error"}

async def get_domains() -> list[str]: #Recupera la lista dei domini supportati dal backend
    try:
        async with httpx.AsyncClient() as client: #apre una sessione di rete come client(si chiude in automatico poichè aperto nella with)
            resp = await client.get(f"{BACKEND_URL}/domains", timeout=10) #fa una chiamata get al end point /domains
            resp.raise_for_status() #se il backend ha risposto con un errore (di tipo 4xx o 5xx), lancia un eccezzione
            return resp.json().get("domains", []) #converte la risposta in un jaison e legge la chiave domains
    except Exception:
        return []


async def get_full_gold_standard(domain: str) -> list[dict]: #Recupera tutto il gold standard di un dominio dal backend
    if not domain:
        return []
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{BACKEND_URL}/full_gold_standard",
                params={"domain": domain},
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json().get("gold_standard", [])
    except Exception:
        pass
    return []

async def build_gs_urls(domains: list[str]) -> dict[str, list[str]]: #funzione per mappare ogni dominio alla lista di URL presenti nel GS
    results = await asyncio.gather(*[get_full_gold_standard(d) for d in domains]) #usiamo asyncio.gather per effettuare tutte le chiamate al backend in contemporanea anzicchè una alla volta
    gs_urls = {}
    for domain, entries in zip(domains, results):
        urls = []
        for entry in entries:
            if "url" in entry:
                urls.append(entry["url"])
        gs_urls[domain] = urls
    return gs_urls


async def get_stats() -> Optional[dict]: #Recupera le statistiche aggregate per dominio dal backend
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{BACKEND_URL}/db_stats")
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass
    return None


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):#Pagina principale: carica domini e URL del GS per il menu a tendina
    domains = await get_domains()
    status=await get_status()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "request": request,
            "page":"home",
            "domains": domains,
            "status":status
        },
    )
@app.post("/parse_url",response_class=HTMLResponse)
async def parse_url(request:Request,url:str=Form(...),mode:str=Form("live")): #prende in input form cioè indica di cercare l'url nel corpo della richiesta http
    domains= await get_domains()
    gs_urls= await build_gs_urls(domains)
    local = (mode == "local") #Live: scarica la pagina dal web; Local: usa l'html_text già salvato nel DB
    error=None #inizializziamo per contenere l'eventuale messaggio di errore da restituire
    result=None #per contenere la risposta json
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            parse_response=await client.post(f"{BACKEND_URL}/parse",json={"url":url,"local":local})
            if parse_response.status_code !=200:
                error=f"Errore dal backend ({parse_response.status_code}):{parse_response.text}"
            else:
                parsed=parse_response.json() #trasformiamo la risposta in un json (avrà la froma dei json restituiti dai parser)
                result={
                    "url":parsed.get("url",url),
                    "domain":parsed.get("domain",""),
                    "title":parsed.get("title",""),
                    "parsed_text":parsed.get("parsed_text",""),
                    "html_text":parsed.get("html_text",""),
                    "gold_text":None, #non lo popoliamo, va messo solo se l'url è nel gs
                    "evaluation":None, #stessa cosa di gold_text
                    "judge":None
                }

                gs_response=await client.get(f"{BACKEND_URL}/gold_standard",params={"url":url}) #andiamo ora a cercare il gs del nostro url per il confronto
                if gs_response.status_code ==200:
                    gs_data=gs_response.json()
                    if gs_data: #se l'url non è nei gs gs_data sarà null
                        result["gold_text"]=gs_data.get("gold_text")
                        if result["gold_text"]: #verifichiamo l'esistena del gs
                            evaluation_response=await client.post(f"{BACKEND_URL}/evaluate",json={"parsed_text":result["parsed_text"],"gold_text":result["gold_text"]}) #mandiamo la richiesta di evaluate(prende in input il parsed text e il gs)
                            if evaluation_response.status_code !=200:
                                 error=f"Errore dal backend ({evaluation_response.status_code}):{evaluation_response.text}"
                            else:
                                result["evaluation"]=evaluation_response.json()
                            try:
                                judge_response=await client.post(f"{BACKEND_URL}/evaluate_judge",json={"parsed_text":result["parsed_text"],"gold_text":result["gold_text"]})
                                if judge_response.status_code==200:
                                    result["judge"]=judge_response.json()
                            except Exception:
                                pass
    except httpx.ConnectError:
        error = f"Impossibile connettersi al backend ({BACKEND_URL}). Assicurati che sia in esecuzione."
    except Exception as e:
        error = f"Errore inatteso: {e}"

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "request":request,
            "page":"parser",
            "domains":       domains,
            "gs_urls":       gs_urls,
            "result":        result,
            "error":         error,
            "submitted_url": url,
            "mode":          mode,
            "backend_url":   BACKEND_URL,
        }
    )
@app.get("/parser",response_class=HTMLResponse)
async def parser_get(request:Request):
    domains=await get_domains()
    gs_urls=await build_gs_urls(domains)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "request":request,
            "page":"parser",
            "domains":domains,
            "gs_urls":gs_urls,
            "result":None,
            "error":None,
            "submitted_url":None,
            "mode":"live"
        }
    )


# ════════════════════════ GOLD STANDARD BUILDER (NUOVO) ════════════════════════

@app.get("/gold-standard", response_class=HTMLResponse)
async def gold_standard_get(
    request: Request,
    domain: Optional[str] = None,
    success: Optional[str] = None,
    error: Optional[str] = None,
):
    domains = await get_domains()
    selected_domain = domain if domain in domains else (domains[0] if domains else None)
    gs_entries = await get_full_gold_standard(selected_domain)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "request": request,
            "page": "gold_standard",
            "domains": domains,
            "selected_domain": selected_domain,
            "gs_entries": gs_entries,
            "fetched_html": None,
            "fetched_url": None,
            "error": error,
            "success": success,
        },
    )


@app.post("/gold-standard/fetch", response_class=HTMLResponse)
async def gold_standard_fetch(request: Request, domain: str = Form(...), url: str = Form(...)):
    domains = await get_domains()
    error = None
    fetched_html = None
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            # Riusiamo /parse in modalità live: il parser fa un fetch reale della
            # pagina e restituisce anche l'html_text grezzo necessario per il GS.
            resp = await client.post(f"{BACKEND_URL}/parse", json={"url": url, "local": False})
            if resp.status_code != 200:
                error = f"Errore dal backend ({resp.status_code}): {resp.text}"
            else:
                fetched_html = resp.json().get("html_text", "")
    except httpx.ConnectError:
        error = f"Impossibile connettersi al backend ({BACKEND_URL}). Assicurati che sia in esecuzione."
    except Exception as e:
        error = f"Errore inatteso: {e}"

    gs_entries = await get_full_gold_standard(domain)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "request": request,
            "page": "gold_standard",
            "domains": domains,
            "selected_domain": domain,
            "gs_entries": gs_entries,
            "fetched_html": fetched_html,
            "fetched_url": url,
            "error": error,
            "success": None,
        },
    )


@app.post("/gold-standard/save")
async def gold_standard_save(
    request: Request,
    domain: str = Form(...),
    url: str = Form(...),
    html_text: str = Form(...),
    gold_text: str = Form(...),
):
    error = None
    success = None
    if not gold_text.strip():
        error = "Il testo gold non può essere vuoto."
    else:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r1 = await client.post(f"{BACKEND_URL}/add_web_resource", json={"url": url, "html_text": html_text})
                r2 = await client.post(f"{BACKEND_URL}/add_gold_standard", json={"url": url, "gold_text": gold_text})
                ok1 = r1.status_code == 200 and r1.json().get("status") == "ok"
                ok2 = r2.status_code == 200 and r2.json().get("status") == "ok"
                if ok1 and ok2:
                    success = f"Gold standard salvato per {url}"
                else:
                    error = f"Errore durante il salvataggio nel database (web_resource: {r1.status_code}, gold_standard: {r2.status_code})"
        except httpx.ConnectError:
            error = f"Impossibile connettersi al backend ({BACKEND_URL}). Assicurati che sia in esecuzione."
        except Exception as e:
            error = f"Errore inatteso: {e}"

    # Redirect (303) dopo il POST: un eventuale F5/ricarica della pagina ripete
    # la GET qui sotto, non il salvataggio, evitando il problema del doppio invio.
    params = {"domain": domain}
    if success:
        params["success"] = success
    if error:
        params["error"] = error
    return RedirectResponse(url=f"/gold-standard?{urlencode(params)}", status_code=303)


@app.post("/gold-standard/delete")
async def gold_standard_delete(request: Request, domain: str = Form(...), url: str = Form(...)):
    error = None
    success = None
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.request("DELETE", f"{BACKEND_URL}/gold_standard", json={"url": url})
            if r.status_code == 200 and r.json().get("status") == "ok":
                success = f"Eliminato {url} dal gold standard"
            else:
                error = f"Errore durante l'eliminazione ({r.status_code}): {r.text}"
    except httpx.ConnectError:
        error = f"Impossibile connettersi al backend ({BACKEND_URL}). Assicurati che sia in esecuzione."
    except Exception as e:
        error = f"Errore inatteso: {e}"

    # Redirect (303) dopo il POST: ricaricare la pagina dopo un'eliminazione
    # rifà la GET (sicura) invece di rinviare lo stesso DELETE già eseguito.
    params = {"domain": domain}
    if success:
        params["success"] = success
    if error:
        params["error"] = error
    return RedirectResponse(url=f"/gold-standard?{urlencode(params)}", status_code=303)


# ════════════════════════ STATISTICHE (NUOVO) ════════════════════════

@app.get("/stats", response_class=HTMLResponse)
async def stats_get(request: Request):
    domains = await get_domains()
    stats = await get_stats()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "request": request,
            "page": "stats",
            "domains": domains,
            "stats": stats,
        },
    )