# Voice RAG

Dockerized, multilingual voice-enabled RAG over AI4Bharat MSMARCO-XI.

The central `ResearchHarness` is the server-side improvement seam. See
[`docs/platform-architecture.md`](docs/platform-architecture.md) for the harness, graph,
LLMOps, privacy, memory, tooling, and latency contract.

## Quick start (recommended local development)

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev,ingest]'
make infra-up
```

In two terminals, run:

```bash
make api
make frontend
```

Open http://localhost:5173 when it is available. If another process already owns
that port, Vite now starts on 5174 (or the next free port) and prints the exact URL;
the `/api` proxy works there too. The API runs directly in the Python virtual
environment; only Qdrant and PostgreSQL run in Docker.

Verify the API before opening the UI:

```bash
curl http://127.0.0.1:8000/api/health
```

The OpenCode adapter uses `https://opencode.ai/zen/go/v1` as its base URL and
supports `OPENCODE_GO_API_KEY`/`OPENCODE_GO_BASE_URL` (preferred) or the generic
`OPENCODE_API_KEY`/`OPENCODE_BASE_URL` names. If a
query returns HTTP 502 with an OpenCode authentication message, the local
pipeline is running but the selected key or base URL is not accepted by the
configured provider. Restart `make api` after correcting `.env`.

Until an index is promoted, the health endpoint reports `qdrant: demo` and the API
answers only from the reviewed curated rows in `data/curated/` (Hacker House Goa event
facts and the platform capability entry). It never fabricates dataset facts. Production
mode (`APP_ENV=production` or `REQUIRE_ACTIVE_INDEX=true`) refuses to serve HTTP 503 until a
validated Qdrant alias is active. Real voice requires `ELEVENLABS_API_KEY`, and generated
answers require `OPENCODE_GO_API_KEY` (or the generic OpenCode key).

Run tests locally with `make install test`. Initialize operational tables with `make postgres-init`.

## Build the real MSMARCO-XI index

MSMARCO-XI is a **gated** Hugging Face repository. Create a read token at
https://huggingface.co/settings/tokens and set `HF_TOKEN` in `.env`. The streaming
`datasets` reader also needs Python 3.11 (the `dill` dependency is broken on 3.14), so
the ingestion tooling runs in a dedicated venv:

```bash
make install311          # creates .venv311 with Python 3.11
.venv311/bin/voice-rag-ingest --stream --language hi --limit 1000 --output data/chunks-hi.jsonl
```

Validate a language directly from Hugging Face first (the command above streams the
`train/hintrain.parquet` file). The repo's loading script is stale; ingestion loads the
per-language parquet files directly.

For the actual Qdrant index, start only infrastructure and run the resumable worker:

```bash
make infra-up
make postgres-init
make index-slice          # representative 100-row validation slice across all 14 languages
make index-language LANG=hi VERSION=hi-v1
make index-all VERSION=msmarco-xi-v1
```

The worker downloads each language's parquet file through the authenticated hub client,
embeds bounded batches, writes a versioned temporary collection, validates point counts and
language coverage, then promotes the collection through the `voice_rag_active` alias.
Chunking is multi-strategy and metadata-aware: short passages use sentence-overlap chunks,
long passages use fixed-size windows with overlap, selected passages additionally get
embedding-based semantic chunks, and every query/answer pair is indexed as a `qa_pair`
chunk. Re-running the same version resumes from completed language entries and Qdrant
point IDs are deterministic, so retries are idempotent. The API continues using the
previously promoted alias during indexing.

The complete corpus is approximately 55.6GB before embeddings and temporary/model storage.
Do not build all 14 languages on a 154GB development disk; use a server with a larger disk and
RAM budget. The local slice is for validating the end-to-end path only.

After a real promotion, set `REQUIRE_ACTIVE_INDEX=true` and restart the API. The health endpoint
must report `qdrant: configured`, and the UI must show `INDEX READY` rather than `DEMO INDEX`.

## API

`POST /api/query` accepts `{ "text": "...", "language": "hi" }` or the same shape with a base64 `audio_base64` field. `POST /api/query/stream` accepts the same body and emits Server-Sent Events for transcription, retrieval, generation, answer tokens, and final validation. The final `run.result` contains transcript, detected language, answer, confidence, grounded/refused state, citations, and stage timings.

Provider calls run behind a per-provider circuit breaker with exponential-backoff retries
for transient HTTP statuses, and structured JSON output is re-validated before the answer is
accepted. Guardrails run before retrieval (prompt injection, off-topic, privacy), and a
deterministic overlap check refuses answers that are not grounded in the retrieved evidence.
Every run appends a privacy-safe trace to `data/traces.jsonl` and a row to the
`query_traces` table when PostgreSQL is available.

If `WEB_RESEARCH_ENABLED=true`, MSMARCO-XI is searched first. Configured Firecrawl can provide
automatic read-only search fallback; a user-supplied public URL can be read through Jina
Reader when Firecrawl is not configured. Web citations are labelled separately from dataset
citations. No write-capable external action is exposed.

## Latency and evaluation

The configured latency contract measures retrieval/orchestration separately from hosted STT
and LLM network latency. Measured against the promoted validation slice (`multilingual-e5-small`
embeddings, 40 queries across 14 languages in `evals/dataset.jsonl`):

| Metric | Retrieval/orchestration | End-to-end (incl. hosted LLM) |
|--------|-------------------------|-------------------------------|
| P50    | 17 ms                   | 3.6 s                         |
| P70    | 23 ms                   | 4.2 s                         |
| P95    | 38 ms                   | 8.6 s                         |
| P100   | 47 ms                   | 9.0 s                         |
| Mean   | 20 ms                   | 3.6 s                         |
| Grounding accuracy | 1.0 | 1.0 |

Every percentile of the retrieval/orchestration seam is under the 200ms target; hosted speech
and answer providers dominate the end-to-end numbers and are measured separately by design.

Run the percentiled benchmark against a live index:

```bash
make evaluate QUERIES=evals/dataset.jsonl    # retrieval-mode P50/P70/P95/P100 + grounding accuracy
.venv/bin/voice-rag-evaluate evals/dataset.jsonl --mode end-to-end --output results/latency-e2e.json
```

Provider keys are never committed; use `.env` locally and a secret manager in deployment.
Qdrant and PostgreSQL volumes persist across restarts.

The platform's self-improvement loop is release-based: traces identify failure modes,
reviewed cases enter `evals/dataset.jsonl`, and centrally versioned changes must pass the
deterministic release gate before promotion. User conversations do not silently modify the
shared model or corpus.
