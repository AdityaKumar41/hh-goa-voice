CREATE TABLE IF NOT EXISTS ingestion_jobs (
  id BIGSERIAL PRIMARY KEY, language TEXT NOT NULL, source_split TEXT NOT NULL,
  status TEXT NOT NULL, processed_rows BIGINT NOT NULL DEFAULT 0,
  processed_chunks BIGINT NOT NULL DEFAULT 0, last_source_hash TEXT,
  index_version TEXT NOT NULL, error TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS index_manifests (
  version TEXT PRIMARY KEY, collection TEXT NOT NULL, languages JSONB NOT NULL,
  vector_count BIGINT NOT NULL DEFAULT 0, valid BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), promoted_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS query_traces (
  trace_id TEXT PRIMARY KEY, language TEXT, transcript TEXT, grounded BOOLEAN,
  refused BOOLEAN, timings_ms JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS evaluation_runs (
  id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL, metrics JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

