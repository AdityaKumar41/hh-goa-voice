"""Resumable Hugging Face MSMARCO-XI to versioned Qdrant indexing worker."""

import argparse
import json
import time
from pathlib import Path

from .config import Settings, get_settings
from .core import Chunk
from .indexing import Embedder, QdrantIndexer
from .ingest import (
    LANGUAGES,
    iter_chunks,
    iter_curated_chunks,
    iter_semantic_chunks,
    load_rows,
)
from .metadata import IndexMetadataStore


def _as_chunk(record: dict) -> Chunk:
    return Chunk(
        id=record["id"],
        text=record["text"],
        language=record["language"],
        query_id=str(record["query_id"]),
        selected=bool(record["selected"]),
        strategy=record["strategy"],
        metadata={
            "passage_id": str(record["passage_id"]),
            "source_hash": record["source_hash"],
            **{
                key: str(record[key])
                for key in (
                    "query", "answer", "english_query", "english_answer", "query_type",
                    "source_lang", "target_lang", "meta",
                )
                if key in record
            },
            "source_type": str(record.get("source_type", "dataset")),
            "source_title": str(record.get("source_title", "")),
            "source_url": str(record.get("source_url", "")),
        },
    )


def build_index(
    settings: Settings,
    *,
    languages: list[str],
    split: str,
    limit: int | None,
    version: str,
    manifest_path: Path,
    strategy: str = "adaptive",
) -> dict:
    from qdrant_client import QdrantClient

    collection = f"{settings.qdrant_collection}_{version}"
    client = QdrantClient(url=settings.qdrant_url, timeout=30)
    embedder = Embedder(settings.embedding_model)
    indexer = QdrantIndexer(client, collection, embedder)
    indexer.ensure_collection()
    metadata_store = IndexMetadataStore(settings.postgres_dsn)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("version") != version:
            raise RuntimeError("manifest version does not match requested index version")
    else:
        manifest = {
            "version": version,
            "collection": collection,
            "languages": {},
            "started_at": time.time(),
            "valid": False,
        }

    for language in languages:
        if manifest["languages"].get(language, {}).get("completed"):
            continue
        job_id = metadata_store.start_job(language, split, version)
        rows = load_rows(language, split)
        batch: list[Chunk] = []
        row_count = 0
        chunk_count = 0
        for row in rows:
            row_count += 1
            for record in iter_chunks([row], language, strategy=strategy):
                batch.append(_as_chunk(record))
                chunk_count += 1
            if strategy in {"adaptive", "semantic"}:
                for record in iter_semantic_chunks([row], language, embedder):
                    batch.append(_as_chunk(record))
                    chunk_count += 1
            if len(batch) >= settings.index_batch_size:
                indexer.upsert(batch)
                batch.clear()
            if limit and row_count >= limit:
                break
        if batch:
            indexer.upsert(batch)
        manifest["languages"][language] = {
            "rows": row_count,
            "chunks": chunk_count,
            "completed": True,
        }
        metadata_store.finish_job(job_id, row_count, chunk_count)
        metadata_store.write_manifest(manifest)
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    curated_key = "curated_event"
    if not manifest["languages"].get(curated_key, {}).get("completed"):
        curated_path = Path("data/curated/hacker-house-goa-2026.jsonl")
        curated_rows = [json.loads(line) for line in curated_path.read_text(encoding="utf-8").splitlines()]
        curated_chunks = [_as_chunk(record) for record in iter_curated_chunks(curated_rows)]
        for offset in range(0, len(curated_chunks), settings.index_batch_size):
            indexer.upsert(curated_chunks[offset : offset + settings.index_batch_size])
        manifest["languages"][curated_key] = {"rows": len(curated_rows), "chunks": len(curated_chunks), "completed": True}
        metadata_store.write_manifest(manifest)
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    manifest["point_count"] = indexer.point_count()
    manifest["language_coverage"] = sorted(indexer.language_coverage())
    manifest["valid"] = set(languages).issubset(set(manifest["language_coverage"]))
    manifest["completed_at"] = time.time()
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    metadata_store.write_manifest(manifest)
    metadata_store.close()
    if not manifest["valid"]:
        raise RuntimeError(f"index validation failed: {manifest['language_coverage']}")
    indexer.promote(settings.qdrant_collection)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and promote a MSMARCO-XI Qdrant index")
    parser.add_argument("--language", action="append", dest="languages", choices=LANGUAGES)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--split", default="train")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--version", required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument(
        "--strategy",
        default="adaptive",
        choices=["adaptive", "sentence_overlap", "fixed_overlap", "semantic"],
        help="chunking strategy applied to dataset passages (semantic adds embedding-aware chunks)",
    )
    args = parser.parse_args()
    languages = LANGUAGES if args.all else args.languages or ["hi"]
    manifest = args.manifest or Path("data/manifests") / f"{args.version}.json"
    result = build_index(
        get_settings(),
        languages=languages,
        split=args.split,
        limit=args.limit,
        version=args.version,
        manifest_path=manifest,
        strategy=args.strategy,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
