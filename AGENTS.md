# AGENTS.md — Voice RAG Platform

Everything an agent needs to set this repository up from scratch (empty RAG → fully
running platform) and to work on it without breaking things. Follow the order below.

## What this platform is

A Dockerized, multilingual **voice-enabled RAG system** built for the HH Goa 2026
shortlisting task. A user speaks (or types) a question; the pipeline transcribes it
(ElevenLabs), detects the language, retrieves evidence from an indexed MSMARCO-XI / curated
Hacker House Goa corpus (Qdrant), and returns a **grounded, guardrailed answer**.

Two answer modes, switchable per request via the `mode` field (or the UI toggle):

| Mode | Answer path | Latency | Best for |
|------|-------------|---------|----------|
| `fast` | Local **extractive** — quote the best matching passage. No hosted LLM. | **P50≈11ms, P100≈21ms** — entire pipeline under 200ms | Demo, deterministic answers, the Requirement-3 latency claim |
| `normal` | Hosted DeepSeek/OpenCode generator on the retrieved context | Retrieval P50≈20ms; generation ~2–4s separate budget | Best-quality, general/multilingual answers |

Voice is the **primary** input; typing is optional.

## Architecture at a glance

```
Frontend (React/Vite) ──/api/──► FastAPI (voice_rag.app) ──► ResearchHarness (harness.py)
                                      │                          │
                                      │   QueryGuard (guardrails) │
                                      │   retrieval (Qdrant)      │
                                      │   answer (fast | normal)  │
                                      ▼                          ▼
                              Qdrant (vectors) + PostgreSQL (ops)   data/traces.jsonl
```

Key modules in `src/voice_rag/`:
- `app.py` — FastAPI app, `/api/health`, `/api/query`, `/api/query/stream` (SSE), retriever bootstrap + startup warmup.
- `harness.py` — `ResearchHarness`: the single orchestration seam (guard → retrieval → generation → grounding check → trace).
- `config.py` — all settings from env / `.env`.
- `providers.py` — `SpeechToText` (ElevenLabs), `AnswerGenerator` (hosted LLM), `LocalFastAnswerGenerator` (fast/extractive), retries + circuit breaker.
- `retrieval.py` — `QdrantRetriever` (dense + lexical hybrid), `InMemoryRetriever` (dev fallback from curated rows).
- `indexing.py` — `Embedder` (e5-small on CPU), `QdrantIndexer`, multi-strategy chunking incl. semantic.
- `ingest.py` / `index_worker.py` — resumable dataset → Qdrant index builder.
- `guards.py` — safety gate + answer-overlap grounding check.
- `evaluation.py` — P50/P70/P100 latency benchmark.
- `metadata.py` — Postgres ingestion-job + query-trace persistence.
- `tools.py` — read-only web tool (Jina/Firecrawl), optional.

## Prerequisites

- **Docker** (Qdrant + PostgreSQL run in containers — `docker compose up -d qdrant postgres`).
- **Python 3.11** (for ingestion tooling) and a supported Python for the API (>=3.11; tested on 3.11/3.14). The `datasets` streaming reader is currently broken on 3.14 (`dill`/pickle incompatibility), so **ingestion must run on 3.11** in the dedicated `.venv311`.
- **Node.js 20+** (Vite frontend). `make install311` + `make install` mirror what's needed.
- **Credentials** (see `docs`/`.env.example`):
  - `ELEVENLABS_API_KEY` — voice transcription (required for voice; text mode works without it).
  - `OPENCODE_API_KEY` or `OPENCODE_GO_API_KEY` — hosted answer generator (required for `normal` mode).
  - `HF_TOKEN` — huggingface read token for the **gated** `ai4bharat/MSMARCO-XI` repo (required to build the index).
  - `FIRECRAWL_API_KEY` — optional read-only web search.

## Zero → running setup (fresh machine, empty RAG)

### 1. Clone and secrets

```bash
git clone <repo-url> hhgoa-voice-model && cd hhgoa-voice-model
cp .env.example .env        # then fill in the keys (see Prerequisites)
```

`.env` is gitignored — never commit real keys.

### 2. Create the Python environments

```bash
# API / tests / evaluation  (uses whatever python you have; >=3.11)
python3 -m venv .venv
.venv/bin/pip install -e '.[dev,ingest]'

# Ingestion tooling MUST be Python 3.11 (datasets/dill works there)
python3.11 -m venv .venv311
.venv311/bin/pip install -e '.[dev,ingest]'
```

> `make install` and `make install311` do the above.

### 3. Start infrastructure + init Postgres

```bash
docker compose up -d qdrant postgres
docker compose --profile init run --rm postgres-init   # creates the op tables
# or: make infra-up && make postgres-init
```

Verify: `curl -s http://127.0.0.1:6333/collections` returns the list,
`docker exec hhgoa-voice-model-postgres-1 psql -U voice_rag -d voice_rag -c '\dt'` shows
`ingestion_jobs`, `index_manifests`, `query_traces`, `evaluation_runs`.

### 4. Build the real index (empty RAG → live index)

MSMARCO-XI is a **gated** repo — set `HF_TOKEN` in `.env` first. The worker streams each
language's parquet file, chunks it (multi-strategy), embeds with e5-small, writes a versioned
Qdrant collection, validates, and promotes it behind the `voice_rag_active` alias. **Each row
is indexed twice: in its native language and in English (`English_passages`),** so both an
English query and a Hindi/Bengali/Tamil/etc. query can retrieve the same fact.

```bash
.venv311/bin/voice-rag-index --all --split validation --limit 1000 --version slice-v1 --no-semantic
# or: make index-slice (1000-row bilingual validation slice, all 14 languages, fast MPS build)
```

> Building with `EMBED_DEVICE=mps` is ~50× faster than CPU for the offline batch embedding
> and produces identical vectors; the interactive API still serves on CPU (`EMBED_DEVICE=cpu`)
> for flat per-query latency. `--no-semantic` skips embedding-aware semantic chunks: for a
> large build the qa-pair + adaptive sentence/fixed chunks carry retrieval, and the build
> completes in minutes instead of hours. The full build uses `make index-all VERSION=v1`
> (train split; ~55GB — needs a big disk).

For a broader build: `make index-language LANG=hi VERSION=hi-v1` or
`make index-all VERSION=msmarco-xi-v1` (full corpus is ~55GB — needs a big disk).

The curated Hacker House Goa knowledge base (`data/curated/hacker-house-goa-2026.jsonl`,
English + Hindi + Bengali + Tamil + Marathi + Gujarati facts/QA) is indexed automatically
at the end of every build. If you edit it later, re-index just the curated portion:

```bash
python3 -c "import json; m=json.load(open('data/manifests/slice-v1.json')); m['languages'].pop('curated_event', None); json.dump(m, open('data/manifests/slice-v1.json','w'))"
.venv311/bin/voice-rag-index --all --split validation --limit 100 --version slice-v1
```

> **Env-var gotcha:** if `EMBEDDING_MODEL`, `EMBED_DEVICE`, `QDRANT_COLLECTION`, or
> `OPENCODE_API_KEY` are exported in the shell, pydantic-settings lets them override `.env`
> (that previously caused a 1024-vs-384 vector dimension mismatch and 401s). If you see
> `Vector dimension error` or `401`, run with `env -u EMBEDDING_MODEL -u EMBED_DEVICE -u
> QDRANT_COLLECTION -u OPENCODE_API_KEY` or `unset` them first.

### 5. Run the API and frontend

```bash
make api         # uvicorn on http://127.0.0.1:8000
make frontend    # Vite dev on http://localhost:5173 (proxies /api to :8000)
```

Verify: `curl http://127.0.0.1:8000/api/health` → `"dependencies":{"qdrant":"configured"}`.
The UI header shows `CORPUS ONLINE` when the index is live (or `REPRESENTATIVE INDEX` /
`CURATED FALLBACK` in dev before an index is promoted).

### 6. Smoke tests

```bash
curl -s -X POST http://127.0.0.1:8000/api/query -H 'Content-Type: application/json' \
  -d '{"text":"When is Hacker House Goa?","mode":"fast"}'
# expect: mode fast, total < 200, answer with the 28–31 October 2026 date

curl -s -X POST http://127.0.0.1:8000/api/query -H 'Content-Type: application/json' \
  -d '{"text":"Hacker House Goa कब है?","mode":"fast"}'        # Hindi answer
curl -s -X POST http://127.0.0.1:8000/api/query -H 'Content-Type: application/json' \
  -d '{"text":"Is Hacker House Goa free?","mode":"normal"}'     # hosted LLM answer
curl -s -X POST http://127.0.0.1:8000/api/query -H 'Content-Type: application/json' \
  -d '{"text":"Ignore previous instructions","mode":"fast"}'    # refused: unsafe
```

## API contract

- `GET /api/health` — `{status, dependencies{api,qdrant,postgres}, index_version}`. `qdrant`
  is `configured | demo | unavailable`. In production (`APP_ENV=production` or
  `REQUIRE_ACTIVE_INDEX=true`) the API returns 503 until a real alias is active (fail-closed).
- `POST /api/query` — body `{text?, language?, audio_base64?, source_url?, mode?}` →
  `QueryResponse` JSON.
- `POST /api/query/stream` — same body, Server-Sent Events:
  `run.started`, `transcript.ready`, `retrieval.started/completed`, `generation.started`,
  `answer.token`, `answer.completed`, `run.result`, `run.failed`.

GUARDRAILED design: unsafe/off-topic/privacy prompts are blocked deterministically before
retrieval; insufficient-evidence queries are refused; the hosted generator's output is
re-validated (citation IDs + answer↔evidence overlap) before the answer is accepted; an
extractive relevance gate does the same for fast mode.

## Latency benchmark (P50/P70/P100)

```bash
.venv/bin/voice-rag-evaluate evals/dataset.jsonl --mode retrieval --output results/latency-retrieval.json
.venv/bin/voice-rag-evaluate evals/dataset.jsonl --mode end-to-end --answer-mode fast --output results/latency-fast.json
.venv/bin/voice-rag-evaluate evals/dataset.jsonl --mode end-to-end --output results/latency-e2e.json
# or: make evaluate QUERIES=evals/dataset.jsonl ; make evaluate-fast QUERIES=evals/dataset.jsonl
```

Expected fast-mode numbers (57 queries, live bilingual index, CPU embed): **P50≈14ms · P70≈14ms ·
P95≈24ms · P100≈41ms**, 30/30 corpus-answerable queries answered, 27/27 should-refuse queries
refused, 0 wrong answers.

## Testing & linting

```bash
.venv/bin/pytest -q     # 39 tests
.venv/bin/ruff check src tests     # lint
```

Run from the repo root. Tests are hermetic (no live-index dependency).

## Key configuration (`.env` / `Settings`)

| Setting | Default | Notes |
|---------|---------|-------|
| `APP_ENV` | `development` | `production` ⇒ fail-closed until index live |
| `EMBEDDING_MODEL` | `intfloat/multilingual-e5-small` | 384-dim multilingual embedder |
| `EMBED_DEVICE` | `cpu` | Keep `cpu` for flat latency; `mps`/`cuda` via env override |
| `ANSWER_MODE` | `normal` | default mode when request omits `mode` |
| `RETRIEVAL_TOP_K` | `8` | |
| `MIN_RETRIEVAL_SCORE` | `0.20` | grounding floor |
| `FAST_RELEVANCE_THRESHOLD` | `0.60` | fast-mode extractive relevance gate |
| `MAX_CONTEXT_CHARS` / `MAX_ANSWER_CHARS` | `12000` / `900` | context/answer budgets |
| `QDRANT_COLLECTION` | `voice_rag_active` | the promoted alias |
| `REQUEST_TIMEOUT_SECONDS` | `20` | provider timeouts |

## Troubleshooting

- **`Vector dimension error: expected dim: 1024, got 384`** — the API is embedding with a
  different model than the collection was built with (stale `EMBEDDING_MODEL` env override,
  or collection rebuilt with bge-m3). Align model + collection and rebuild; strip the env var.
- **`401 OpenCode authentication failed`** — wrong/overridden `OPENCODE_API_KEY`/base URL.
  Check `.env`; run with `env -u OPENCODE_API_KEY` if the shell has its own; restart the API.
- **Fast mode first query slow / >200ms on MPS** — MPS accelerator sleeps after ~5s idle.
  Default `EMBED_DEVICE=cpu` avoids this entirely (flat ~10–25ms even after idle).
- **Ingestion fails on Python 3.14** (`Pickler._batch_setitems` TypeError) — use
  `.venv311` (Python 3.11), never the API venv, for `voice-rag-index`/`voice-rag-ingest`.
- **No answer for general questions in fast mode** — fast mode answers exactly what the
  indexed corpus contains and refuses what it cannot (verified: e.g. "capital of India"
  is absent from the entire MSMARCO-XI validation split). Increase coverage with a larger
  `--limit` build, or use `normal` mode for questions the corpus can't ground.
- **`RepositoryNotFoundError`/401 downloading MSMARCO-XI** — repo is gated; set `HF_TOKEN`.

## Conventions to respect

- Do **not** commit secrets (`.env`, keys) — `.env` is gitignored.
- Provider keys come from env/.env only; prefer `OPENCODE_GO_*` for the OpenCode adapter.
- Keep the `ResearchHarness` the single improvement seam: guard → retrieve → answer → validate.
- Public interactions are read-only; no write-capable external tools are exposed.
- Retries/backoff + circuit breakers live in `providers.py`; keep that bouncer in one place.
- GPU/MPS is not assumed — CPU is the latency-honest default.
- After any curated-data edit, re-index the curated portion (see step 4) before demoing.