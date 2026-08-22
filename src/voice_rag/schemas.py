from typing import Literal

from pydantic import BaseModel, Field

SUPPORTED_LANGUAGES = {
    "as",
    "bn",
    "gu",
    "hi",
    "kn",
    "ml",
    "mr",
    "ne",
    "or",
    "pa",
    "sa",
    "ta",
    "te",
    "ur",
    "en",
}


class Citation(BaseModel):
    passage_id: str
    language: str
    text: str
    score: float
    selected: bool = False
    source_type: Literal["dataset", "event", "web", "platform"] = "dataset"
    source_title: str | None = None


class QueryRequest(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=4000)
    language: str | None = None
    audio_base64: str | None = None
    source_url: str | None = Field(default=None, max_length=2000)
    mode: Literal["normal", "fast"] | None = None


class QueryResponse(BaseModel):
    trace_id: str
    transcript: str
    detected_language: str
    answer: str
    confidence: float
    grounded: bool
    refused: bool
    refusal_reason: str | None = None
    citations: list[Citation] = Field(default_factory=list)
    timings_ms: dict[str, float] = Field(default_factory=dict)
    mode: Literal["normal", "fast"] = "normal"


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    dependencies: dict[str, str]
    index_version: str
