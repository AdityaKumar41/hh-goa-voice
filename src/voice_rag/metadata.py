"""Best-effort operational metadata writes for indexing and query operations."""

import json
import logging

logger = logging.getLogger(__name__)


class IndexMetadataStore:
    def __init__(self, dsn: str):
        self.connection = None
        try:
            import psycopg

            self.connection = psycopg.connect(dsn, autocommit=True)
        except Exception:  # noqa: BLE001 - indexing must remain resumable if analytics is down
            logger.warning("PostgreSQL metadata is unavailable; continuing with JSON manifest")

    def start_job(self, language: str, split: str, version: str):
        if not self.connection:
            return None
        with self.connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO ingestion_jobs (language, source_split, status, index_version) "
                "VALUES (%s, %s, 'running', %s) RETURNING id",
                (language, split, version),
            )
            return cursor.fetchone()[0]

    def finish_job(self, job_id, rows: int, chunks: int, status: str = "completed", error=None):
        if not self.connection or job_id is None:
            return
        with self.connection.cursor() as cursor:
            cursor.execute(
                "UPDATE ingestion_jobs SET status=%s, processed_rows=%s, "
                "processed_chunks=%s, error=%s, updated_at=now() WHERE id=%s",
                (status, rows, chunks, error, job_id),
            )

    def write_manifest(self, manifest: dict):
        if not self.connection:
            return
        with self.connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO index_manifests (version, collection, languages, vector_count, valid) "
                "VALUES (%s, %s, %s::jsonb, %s, %s) ON CONFLICT (version) DO UPDATE SET "
                "languages=excluded.languages, vector_count=excluded.vector_count, valid=excluded.valid",
                (
                    manifest["version"], manifest["collection"], json.dumps(manifest["languages"]),
                    manifest.get("point_count", 0), manifest.get("valid", False),
                ),
            )

    def close(self):
        if self.connection:
            self.connection.close()


class QueryTraceStore:
    """Best-effort persistence of query traces for operational analytics."""

    def __init__(self, dsn: str):
        self.connection = None
        try:
            import psycopg

            self.connection = psycopg.connect(dsn, autocommit=True)
        except Exception:  # noqa: BLE001 - query serving must not depend on analytics
            logger.warning("PostgreSQL is unavailable; query traces stay on disk")

    def write(
        self,
        trace_id: str,
        *,
        language: str,
        transcript: str,
        grounded: bool,
        refused: bool,
        timings_ms: dict,
    ) -> None:
        if not self.connection:
            return
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO query_traces "
                    "(trace_id, language, transcript, grounded, refused, timings_ms) "
                    "VALUES (%s, %s, %s, %s, %s, %s::jsonb) ON CONFLICT (trace_id) DO NOTHING",
                    (trace_id, language, transcript[:2000], grounded, refused, json.dumps(timings_ms)),
                )
        except Exception:
            logger.warning("query trace write failed", exc_info=True)

    def close(self):
        if self.connection:
            self.connection.close()
