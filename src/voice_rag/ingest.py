"""Resumable dataset-to-Qdrant ingestion primitives.

The default command processes one or more language configurations in bounded batches.
It intentionally keeps embedding and Qdrant clients behind small interfaces so a
large production run can be resumed and tested without downloading the full corpus.
"""

import argparse
import json
from collections.abc import Iterable
from pathlib import Path

from .config import get_settings
from .core import Chunk, chunk_text, content_hash, normalize_text
from .indexing import chunk_semantic

LANGUAGES = ["as", "bn", "gu", "hi", "kn", "ml", "mr", "ne", "or", "pa", "sa", "ta", "te", "ur"]

# ai4bharat/MSMARCO-XI ships per-language parquet files (the repo loading script is stale).
# Telugu has no train split; both splits are keyed by these files.
LANGUAGE_PARQUET = {
    "as": {"train": "train/asmtrain.parquet", "validation": "validation/asmval.parquet"},
    "bn": {"train": "train/bentrain.parquet", "validation": "validation/benval.parquet"},
    "gu": {"train": "train/gujtrain.parquet", "validation": "validation/gujval.parquet"},
    "hi": {"train": "train/hintrain.parquet", "validation": "validation/hinval.parquet"},
    "kn": {"train": "train/kantrain.parquet", "validation": "validation/kanval.parquet"},
    "ml": {"train": "train/maltrain.parquet", "validation": "validation/malval.parquet"},
    "mr": {"train": "train/martrain.parquet", "validation": "validation/marval.parquet"},
    "ne": {"train": "train/neptrain.parquet", "validation": "validation/nepval.parquet"},
    "or": {"train": "train/oritrain.parquet", "validation": "validation/orival.parquet"},
    "pa": {"train": "train/pantrain.parquet", "validation": "validation/panval.parquet"},
    "sa": {"train": "train/santrain.parquet", "validation": "validation/sanval.parquet"},
    "ta": {"train": "train/tamtrain.parquet", "validation": "validation/tamval.parquet"},
    "te": {"train": None, "validation": "validation/telval.parquet"},
    "ur": {"train": "train/urdtrain.parquet", "validation": "validation/urdval.parquet"},
}


def resolve_parquet(language: str, split: str) -> str:
    path = LANGUAGE_PARQUET[language].get(split)
    if not path:
        raise RuntimeError(f"language {language!r} has no {split} split on the MSMARCO-XI hub")
    return path


def load_rows(language: str, split: str = "train"):
    """Stream real MSMARCO-XI rows for one language, bypassing the stale loading script.

    Downloads the language's parquet file through the authenticated hub client, then
    streams it from disk. Requires ``HF_TOKEN`` in the environment for the gated repo.
    Telugu has no train split on the hub, so ``train`` silently falls back to
    ``validation`` rather than failing a full build.
    """
    from datasets import load_dataset
    from huggingface_hub import hf_hub_download

    settings = get_settings()
    if not settings.hf_token:
        raise RuntimeError(
            "MSMARCO-XI is a gated repository. Set HF_TOKEN (or HF_TOKEN=... in .env) "
            "to download it."
        )
    path = resolve_parquet(language, split)
    if path is None:
        path = resolve_parquet(language, "validation")
    local = hf_hub_download(
        "ai4bharat/MSMARCO-XI", path, token=settings.hf_token, repo_type="dataset"
    )
    return load_dataset("parquet", data_files={split: local}, split=split, streaming=True)


def iter_curated_chunks(rows: Iterable[dict]):
    """Convert small, reviewed product/event facts into separately labelled chunks."""
    for row in rows:
        text = normalize_text(str(row["text"]))
        if not text:
            continue
        passage_id = content_hash("curated", str(row["id"]), text)
        yield {
            "id": passage_id,
            "text": text,
            "language": str(row.get("language", "en")),
            "query_id": f"curated:{row['id']}",
            "passage_id": passage_id,
            "selected": True,
            "strategy": "curated_fact",
            "source_hash": content_hash("curated", text),
            "source_type": str(row.get("source_type", "event")),
            "source_title": str(row.get("title", row["id"])),
            "source_url": str(row.get("source_url", "")),
        }


def _chunk_record(
    chunk: Chunk,
    *,
    language: str,
    query_id: str,
    passage_id: str,
    selected: bool,
    source_hash: str,
    common: dict,
) -> dict:
    return {
        "id": chunk.id,
        "text": chunk.text,
        "language": language,
        "query_id": query_id,
        "passage_id": passage_id,
        "selected": selected,
        "strategy": chunk.strategy,
        "source_hash": source_hash,
        **common,
    }


def iter_chunks(rows: Iterable[dict], language: str, strategy: str = "adaptive"):
    """Yield indexed chunk records with metadata-aware, multi-strategy chunking.

    ``strategy`` may be ``adaptive`` (sentence chunking for short passages, fixed-size
    with overlap for longer ones), ``sentence_overlap``, ``fixed_overlap``, or
    ``semantic`` (requires the worker's embedder). Every record keeps the source row
    metadata so retrieval can re-rank and cite with full context. Query-answer pairs
    are emitted as dedicated ``qa_pair`` chunks for direct answer retrieval.

    Each MSMARCO-XI row carries both a translated (native) side and the original English
    side; both are indexed, so an English query retrieves MSMARCO content and a native
    query retrieves the translated content for the same fact.
    """
    seen: set[str] = set()
    for row in rows:
        query_id = str(row.get("query_id", "unknown"))
        common = _row_common(row, language)
        variants = (
            (language, common["query"], common["answer"], _translated_texts(row)),
            ("en", common["english_query"], common["english_answer"], _english_texts(row)),
        )
        for lang, query, answer, texts in variants:
            if query and answer:
                pair_id = content_hash("qa_pair", lang, query_id, query, answer)
                if pair_id not in seen:
                    seen.add(pair_id)
                    yield _chunk_record(
                        Chunk(
                            id=pair_id,
                            text=f"{query} {answer}".strip(),
                            language=lang,
                            query_id=query_id,
                            selected=True,
                            strategy="qa_pair",
                            metadata={},
                        ),
                        language=lang,
                        query_id=query_id,
                        passage_id=pair_id,
                        selected=True,
                        source_hash=content_hash("qa_pair", lang, query, answer),
                        common=common,
                    )
            for index, text in enumerate(texts):
                passage_id = content_hash(lang, query_id, str(index), text)
                if passage_id in seen:
                    continue
                seen.add(passage_id)
                use = strategy
                if strategy == "adaptive":
                    use = "fixed_overlap" if len(text) > 1400 else "sentence_overlap"
                for chunk in chunk_text(
                    text,
                    language=lang,
                    query_id=query_id,
                    passage_id=passage_id,
                    strategy=use,
                ):
                    yield _chunk_record(
                        chunk,
                        language=lang,
                        query_id=query_id,
                        passage_id=passage_id,
                        selected=_is_selected(row, index),
                        source_hash=content_hash(lang, query_id, text),
                        common={**common, "target_lang": str(row.get("target_lang", lang))},
                    )


def iter_semantic_chunks(
    rows: Iterable[dict],
    language: str,
    embedder,
    *,
    max_chars: int = 700,
    overlap: int = 100,
):
    """Embedding-aware chunks for selected passages, complementing deterministic ones."""
    seen: set[str] = set()
    for row in rows:
        query_id = str(row.get("query_id", "unknown"))
        common = _row_common(row, language)
        variants = (
            (language, _translated_texts(row)),
            ("en", _english_texts(row)),
        )
        for lang, texts in variants:
            for index, text in enumerate(texts):
                if not _is_selected(row, index):
                    continue
                passage_id = content_hash(lang, query_id, str(index), text)
                if passage_id in seen:
                    continue
                seen.add(passage_id)
                for chunk in chunk_semantic(
                    text,
                    language=lang,
                    query_id=query_id,
                    passage_id=passage_id,
                    embed=embedder.embed_batch,
                    max_chars=max_chars,
                    overlap=overlap,
                ):
                    yield _chunk_record(
                        chunk,
                        language=lang,
                        query_id=query_id,
                        passage_id=passage_id,
                        selected=True,
                        source_hash=content_hash("semantic", lang, query_id, text),
                        common={**common, "target_lang": str(row.get("target_lang", lang))},
                    )


def _row_common(row: dict, language: str) -> dict:
    return {
        "query": normalize_text(str(row.get("query", ""))),
        "answer": normalize_text(str(row.get("Answer", ""))),
        "english_query": normalize_text(str(row.get("Eng_Query", ""))),
        "english_answer": normalize_text(str(row.get("Eng_Answer", ""))),
        "query_type": str(row.get("query_type", "")),
        "source_lang": str(row.get("source_lang", "")),
        "target_lang": str(row.get("target_lang", language)),
        "meta": json.dumps(row.get("meta", {}), ensure_ascii=False, sort_keys=True),
    }


def _translated_texts(row: dict) -> list[str]:
    passages = row.get("passages", {})
    texts = passages.get("Translated_passages") or []
    return [normalize_text(str(text)) for text in texts if normalize_text(str(text))]


def _english_texts(row: dict) -> list[str]:
    passages = row.get("passages", {})
    texts = passages.get("English_passages") or []
    return [normalize_text(str(text)) for text in texts if normalize_text(str(text))]


def _is_selected(row: dict, index: int) -> bool:
    selected = row.get("passages", {}).get("is_selected") or []
    return bool(selected[index]) if index < len(selected) else False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest MSMARCO-XI into newline-delimited chunk records"
    )
    parser.add_argument("--input", type=Path, help="JSONL fixture or exported dataset rows")
    parser.add_argument("--dataset", default="ai4bharat/MSMARCO-XI")
    parser.add_argument("--split", default="train")
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Read directly from Hugging Face without materializing the dataset",
    )
    parser.add_argument("--limit", type=int, help="Bound a validation run before full ingestion")
    parser.add_argument("--language", default="hi", choices=LANGUAGES)
    parser.add_argument("--output", type=Path, default=Path("data/chunks.jsonl"))
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.input:
        rows = (json.loads(line) for line in args.input.open(encoding="utf-8"))
    elif args.stream:
        rows = load_rows(args.language, args.split)
    else:
        raise SystemExit("provide --input or --stream")
    count = 0
    with args.output.open("a", encoding="utf-8") as target:
        for row in rows:
            for record in iter_chunks([row], args.language):
                target.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
            if args.limit and count >= args.limit:
                break
    print(json.dumps({"language": args.language, "rows": count, "output": str(args.output)}))


if __name__ == "__main__":
    main()
