from pydantic import BaseModel, Field
from typing import Optional, Any

# File contente tutte le strutture dati (Pydantic models) utilizzate dalle API REST del backend. 

class ParseOutput(BaseModel):
    url: str
    domain: str
    title: str
    html_text: str
    parsed_text: str

class PostParseRequest(BaseModel):
    url: str
    local: Optional[bool] = False

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

class EvaluationRequest(BaseModel):
    parsed_text: str
    gold_text: str

class StatusOutput(BaseModel):
    backend: str
    database: str
    ollama: str

class DBSchemaOutput(BaseModel):
    web_resources: dict[str, str]
    gold_standard: dict[str, str]
    parsed_results: dict[str, str]
    evaluation_results: dict[str, str]
    llm_judge_results: dict[str, str]

class AddWebResourceRequest(BaseModel):
    url: str
    html_text: str

class OperationOutput(BaseModel):
    status: str

class AddGoldStandardRequest(BaseModel):
    url: str
    gold_text: str

class DeleteRequest(BaseModel):
    url: str

class DBStatsOutput(BaseModel):
    web_resources: dict[str, int]
    gold_standard: dict[str, int]
    avg_eval: dict[str, Any]
    avg_eval_judge: dict[str, Any]

class AddToGraphRequest(BaseModel):
    url: str

class DeleteGraphRelationRequest(BaseModel):
    subject: str
    relation: str
    object: str

class DeleteGraphNodeRequest(BaseModel):
    node_name: str

class AskGraphRequest(BaseModel):
    question: str

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
    judge_score: float

class JudgeOutput(BaseModel):
    model_name: str
    judge_score: int
    judge_feedback: str