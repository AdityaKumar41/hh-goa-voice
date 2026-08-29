# Hacker House Voice RAG Architecture

This is the source architecture document for the public interactive diagram at
[`/architecture.html`](frontend/public/architecture.html). The deployed frontend
serves that page from its static public assets.

```mermaid
flowchart LR
    U[User\nvoice or text] --> V[Vercel React frontend]
    V -->|HTTPS /api| R[Railway FastAPI API]
    R --> G[Query guard\nprivacy + prompt injection]
    G --> H[ResearchHarness]
    H --> Q[Hybrid retrieval]
    Q --> E[Multilingual E5\nCPU embeddings]
    E --> Z[(Qdrant\nvoice_rag_active alias)]
    H --> F{Answer mode}
    F -->|fast| X[Local extractive answer]
    F -->|normal| L[OpenCode hosted LLM]
    H --> C[Grounding + citation validation]
    X --> C
    L --> C
    C --> O[Grounded response\nSSE or JSON]
    O --> V
    R --> S[ElevenLabs STT\nvoice only]
    S --> H
    H --> P[(Supabase PostgreSQL\nquery traces + metadata)]
    W[Indexer / reindex CLI\nPython 3.11] --> E
    W --> Z
    W --> M[Validated manifest\nthen atomic alias promotion]
```

## Runtime flow

1. The browser sends text or recorded audio to the Railway API.
2. Audio is transcribed by ElevenLabs, then the query guard blocks unsafe or
   irrelevant requests before retrieval.
3. The harness retrieves from the promoted Qdrant alias using multilingual E5
   embeddings and hybrid lexical matching.
4. Fast mode quotes a relevant passage locally. Normal mode asks the hosted
   generator to answer from the retrieved evidence.
5. Citation IDs and answer/evidence overlap are checked before the response is
   returned. Query metadata is written best-effort to PostgreSQL.

## Deployment and data flow

- Vercel hosts the frontend and uses `VITE_API_URL` to reach Railway.
- Railway runs the Dockerized FastAPI service and honors its injected `PORT`.
- Qdrant is an external vector store. The `voice_rag_active` alias currently
  points to the curated production collection.
- Supabase PostgreSQL stores operational traces and ingestion metadata. Database
  persistence is optional for serving, but the DSN must resolve for it to work.
- Index builds write a versioned collection, validate it, and promote the alias
  atomically so queries do not see a partial index.
