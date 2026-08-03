import httpx
from urllib.parse import urlparse
from fastapi import APIRouter, Request, HTTPException
from src.rest.structures import (
    StatusOutput, DBSchemaOutput, AddWebResourceRequest, 
    OperationOutput, AddGoldStandardRequest, DeleteRequest, DBStatsOutput
)

router = APIRouter(tags=["Database & Status"])

@router.get("/status")
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
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get("http://ollama:11434/api/tags")
            ollama_status = "ok" if r.status_code == 200 else "error"
    except Exception:
        ollama_status = "error"

    return StatusOutput(backend="ok", database=db_status, ollama=ollama_status)

@router.get("/db_schema")
async def db_schema() -> DBSchemaOutput:
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

@router.post("/add_web_resource")
async def add_web_resource(body: AddWebResourceRequest, http_request: Request) -> OperationOutput:
    domain = urlparse(body.url).netloc
    conn = http_request.app.state.db
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO web_resources (url, domain, title, html_text) VALUES (?, ?, ?, ?)",
            (body.url, domain, "", body.html_text)
        )
        conn.commit() 
        return OperationOutput(status="ok")
    except Exception:
        return OperationOutput(status="error")
    finally:
        cursor.close() 

@router.post("/add_gold_standard")
async def add_gold_standard(body: AddGoldStandardRequest, http_request: Request) -> OperationOutput:
    conn = http_request.app.state.db
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT url FROM web_resources WHERE url=?", (body.url,))
        if not cursor.fetchone():
            return OperationOutput(status="error")
        cursor.execute(
            "INSERT INTO gold_standard (url, gold_text) VALUES (?, ?)",
            (body.url, body.gold_text)
        )
        conn.commit()
        return OperationOutput(status="ok")
    except Exception:
        return OperationOutput(status="error")
    finally:
        cursor.close()

@router.delete("/web_resource")
async def delete_web_resource(body: DeleteRequest, http_request: Request) -> OperationOutput:
    conn = http_request.app.state.db
    cursor = conn.cursor()
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

@router.delete("/gold_standard")
async def delete_gold_standard(body: DeleteRequest, http_request: Request) -> OperationOutput:
    conn = http_request.app.state.db
    cursor = conn.cursor()
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

@router.get("/db_stats")
async def db_stats(http_request: Request) -> DBStatsOutput:
    conn = http_request.app.state.db
    cursor = conn.cursor()
    cursor.execute("SELECT domain, COUNT(*) FROM web_resources GROUP BY domain")
    conteggio_web = {row[0]: row[1] for row in cursor.fetchall()}

    cursor.execute(
        """
        SELECT wr.domain, COUNT(*)
        FROM gold_standard gs
        JOIN web_resources wr ON gs.url = wr.url
        GROUP BY wr.domain
        """
    )
    conteggio_gold = {row[0]: row[1] for row in cursor.fetchall()}

    media_valutazione = {domain: {"token_level_eval": {"precision": 0.0, "recall": 0.0, "f1": 0.0}} for domain in conteggio_web}
    avg_eval_judje = {domain: {"judge_score": 0.0} for domain in conteggio_web}

    cursor.execute(
        """
        SELECT wr.domain, AVG(er.precision_score), AVG(er.recall_score), AVG(er.f1_score)
        FROM evaluation_results er
        JOIN web_resources wr ON er.url = wr.url
        GROUP BY wr.domain
        """
    )
    for row in cursor.fetchall():
        media_valutazione[row[0]] = {"token_level_eval": {"precision": row[1] or 0.0, "recall": row[2] or 0.0, "f1": row[3] or 0.0}}

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
    return DBStatsOutput(web_resources=conteggio_web, gold_standard=conteggio_gold, avg_eval=media_valutazione, avg_eval_judge=avg_eval_judje)