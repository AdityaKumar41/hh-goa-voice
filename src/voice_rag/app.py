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
    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(url=settings.qdrant_url, timeout=1)
        client.get_collection(settings.qdrant_collection)
        embedder = Embedder(settings.embedding_model)
        # Warm the model (load + realistic inference) so the first user query never
        # pays model-load or accelerator kernel-compilation latency. MPS compiles a
        # separate graph per batch shape, so warm both the single-query shape and a
        # larger batch (indexing) shape.
        embedder._load()
        embedder.embed_batch(["Who can attend Hacker House Goa?"])
        embedder.embed_batch(["What is the capital of India?" for _ in range(8)])
        dense = QdrantRetriever(client, settings.qdrant_collection, embedder)
        return HybridRetriever(dense)
    except Exception:  # noqa: BLE001 - startup must tolerate an unavailable optional index
        if settings.require_active_index or settings.app_env == "production":
            # Fail closed: production must not serve answers from demo or curated text.
            return InMemoryRetriever([])
        # Local development before the first index promotion: honest curated rows only.
        return InMemoryRetriever(curated_documents())


pipeline = QueryPipeline(settings, retriever=build_retriever())


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Warm the full retrieval path (embed + Qdrant connection + lexical merge) a few
    # times so the first user request never pays accelerator graph compilation or
    # connection setup. A single warmup can leave a residual first-call cost.
    for _ in range(3):
        try:
            await pipeline.retriever.search("Is Hacker House Goa free?", "en", 4)
        except Exception:
            logger.warning("startup warmup search failed", exc_info=True)
    yield


app = FastAPI(title="Voice RAG API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


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
    return HealthResponse(
        status="ok" if qdrant_status != "unavailable" else "degraded",
        dependencies={"api": "ok", "qdrant": qdrant_status, "postgres": "configured"},
        index_version=settings.index_version,
    )


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
