import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .config import get_settings
from .indexing import Embedder
from .pipeline import QueryPipeline
from .providers import ProviderError
from .retrieval import HybridRetriever, InMemoryRetriever, QdrantRetriever, SearchDocument
from .schemas import HealthResponse, QueryRequest, QueryResponse
from .tools import ToolError

logger = logging.getLogger(__name__)
settings = get_settings()

CURATED_PATH = Path("data/curated/hacker-house-goa-2026.jsonl")
_retriever_error: str | None = None


def curated_documents() -> list[SearchDocument]:
    """Reviewed, source-labelled development documents (event facts + platform).

    These are real curated rows, never fabricated dataset evidence. In production a
    promoted Qdrant alias must exist; this fallback only keeps local development usable.
    """
    if not CURATED_PATH.exists():
        return []
    documents = []
    for line in CURATED_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        text = str(row.get("text", "")).strip()
        if not text:
            continue
        documents.append(
            SearchDocument(
                id=str(row["id"]),
                text=text,
                language=str(row.get("language", "en")),
                score=0.95,
                selected=True,
                source_type=str(row.get("source_type", "event")),
                source_title=str(row.get("title") or row["id"]),
            )
        )
    return documents


def build_retriever():
    global _retriever_error
    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
            timeout=1,
        )
        client.get_collection(settings.qdrant_collection)
        embedder = Embedder(settings.embedding_model)
        dense = QdrantRetriever(client, settings.qdrant_collection, embedder)
        return HybridRetriever(dense)
    except Exception as exc:  # noqa: BLE001 - startup must tolerate an unavailable optional index
        _retriever_error = f"{type(exc).__name__}: {str(exc).splitlines()[0][:240]}"
        logger.error("Qdrant retriever initialization failed: %s", _retriever_error)
        if settings.require_active_index or settings.app_env == "production":
            # Fail closed: production must not serve answers from demo or curated text.
            return InMemoryRetriever([])
        # Local development before the first index promotion: honest curated rows only.
        return InMemoryRetriever(curated_documents())


pipeline = QueryPipeline(settings, retriever=build_retriever())


@asynccontextmanager
async def lifespan(_app: FastAPI):
    def warm_retriever_sync() -> None:
        # Do not block the web server from binding its port while a HuggingFace model
        # downloads. Railway/Render health probes must be able to reach /api/health
        # immediately after the container starts.
        for _ in range(3):
            try:
                asyncio.run(pipeline.retriever.search("Is Hacker House Goa free?", "en", 4))
            except Exception:
                logger.warning("background retrieval warmup failed", exc_info=True)

    warmup_task = asyncio.create_task(asyncio.to_thread(warm_retriever_sync))
    yield
    warmup_task.cancel()
    try:
        await warmup_task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Voice RAG API", version="0.1.0", lifespan=lifespan)
_production_frontend_origin = "https://hh-goa-voice-olive.vercel.app"
_cors_origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
# Replace the permissive default with explicit origins so browsers receive a concrete
# allow-origin value. This also keeps the deployed Vercel client reachable if a
# Railway variable is stale or contains only a local origin.
if "*" in _cors_origins:
    _cors_origins = [_production_frontend_origin, "http://localhost:5173", "http://127.0.0.1:5173"]
elif _production_frontend_origin not in _cors_origins:
    _cors_origins.append(_production_frontend_origin)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins or ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/benchmark")
async def benchmark(limit: int = 40, mode: str = "fast") -> dict:
    """Live latency analytics: P50/P70/P95/P100 over the eval queries.

    Runs real queries through the already-warm pipeline (fast mode is local, so it
    completes in about a second). This is the Requirement-4 latency-analytics surface.
    """
    from pathlib import Path as _Path

    from .benchmark import run_benchmark

    rows = [
        json.loads(line)
        for line in _Path("evals/dataset.jsonl").read_text().splitlines()
        if line.strip()
    ]
    if not rows:
        return {"error": "evals/dataset.jsonl is empty"}
    return await run_benchmark(pipeline, rows, answer_mode=mode, limit=max(1, min(limit, len(rows))))


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    active_index = isinstance(pipeline.retriever, (QdrantRetriever, HybridRetriever))
    qdrant_status = "configured" if active_index else (
        "unavailable"
        if settings.require_active_index or settings.app_env == "production"
        else "demo"
    )
    if not getattr(pipeline.trace_db, "connection", None):
        pipeline.trace_db.reconnect()
    postgres_status = "configured" if getattr(pipeline.trace_db, "connection", None) else "unavailable"
    response = HealthResponse(
        status="ok" if qdrant_status != "unavailable" else "degraded",
        dependencies={"api": "ok", "qdrant": qdrant_status, "postgres": postgres_status},
        index_version=settings.index_version,
    )
    if _retriever_error:
        response.dependencies["qdrant_detail"] = _retriever_error
    if postgres_status == "unavailable":
        postgres_error = getattr(
            pipeline.trace_db,
            "connection_error",
            "metadata connection unavailable; check DATABASE_URL",
        )
        if "Network is unreachable" in postgres_error and ":" in postgres_error:
            postgres_error += "; use the Supabase IPv4 pooler URL instead of the direct db host"
        response.dependencies["postgres_detail"] = postgres_error
    return response


def _require_active_index() -> None:
    if not isinstance(pipeline.retriever, (QdrantRetriever, HybridRetriever)) and (
        settings.require_active_index or settings.app_env == "production"
    ):
        raise HTTPException(
            status_code=503,
            detail="No validated search index is active. Promote an index before serving.",
        )


@app.post("/api/query", response_model=QueryResponse)
async def query(
    request: QueryRequest, x_user_id: str = Header(default="anonymous")
) -> QueryResponse:
    _require_active_index()
    try:
        return await pipeline.run(request, user_id=x_user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ToolError as exc:
        raise HTTPException(status_code=424, detail=str(exc)) from exc


@app.post("/api/query/stream")
async def query_stream(
    request: QueryRequest, x_user_id: str = Header(default="anonymous")
) -> StreamingResponse:
    """Stream observable pipeline events and provider answer deltas over SSE."""
    _require_active_index()
    queue: asyncio.Queue[tuple[str, dict]] = asyncio.Queue()

    def on_event(name: str, data: dict) -> None:
        queue.put_nowait((name, data))

    async def on_token(token: str) -> None:
        queue.put_nowait(("answer.token", {"token": token}))

    async def events():
        task = asyncio.create_task(
            pipeline.run(request, user_id=x_user_id, on_event=on_event, on_token=on_token)
        )
        try:
            while True:
                if task.done() and queue.empty():
                    break
                try:
                    name, data = await asyncio.wait_for(queue.get(), timeout=0.25)
                except TimeoutError:
                    continue
                yield f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
            response = await task
            # Refusal paths return before the normal harness event callback.
            yield f"event: run.result\ndata: {json.dumps(response.model_dump(), ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001 - serialize failures for the browser
            if not task.done():
                task.cancel()
            yield f"event: run.failed\ndata: {json.dumps({'detail': str(exc)})}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
