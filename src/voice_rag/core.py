import hashlib
import re
import unicodedata
from dataclasses import dataclass


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    return re.sub(r"\s+", " ", value).strip()


def content_hash(*parts: str) -> str:
    joined = "\x1f".join(normalize_text(part) for part in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def detect_language(text: str, requested: str | None = None) -> str:
    if requested:
        return requested.lower().split("-")[0]
    ranges = {
        "hi": ("\u0900", "\u097f"),
        "bn": ("\u0980", "\u09ff"),
        "pa": ("\u0a00", "\u0a7f"),
        "gu": ("\u0a80", "\u0aff"),
        "or": ("\u0b00", "\u0b7f"),
        "ta": ("\u0b80", "\u0bff"),
        "te": ("\u0c00", "\u0c7f"),
        "kn": ("\u0c80", "\u0cff"),
        "ml": ("\u0d00", "\u0d7f"),
    }
    scores = {
        lang: sum(start <= char <= end for char in text) for lang, (start, end) in ranges.items()
    }
    best, score = max(scores.items(), key=lambda item: item[1])
    return best if score else "en"


@dataclass(frozen=True)
class Chunk:
    id: str
    text: str
    language: str
    query_id: str
    selected: bool
    strategy: str
    metadata: dict[str, str]


def _split_sentences(clean: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?।॥])\s+", clean) if part.strip()]


def _sentence_chunks(clean: str, max_chars: int, overlap: int) -> list[str]:
    sentences = _split_sentences(clean)
    chunks: list[str] = []
    current = ""
    for sentence in sentences or [clean]:
        candidate = f"{current} {sentence}".strip()
        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = f"{current[-overlap:]} {sentence}".strip()
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _fixed_chunks(clean: str, max_chars: int, overlap: int) -> list[str]:
    if len(clean) <= max_chars:
        return [clean]
    chunks: list[str] = []
    start = 0
    step = max(1, max_chars - overlap)
    while start < len(clean):
        end = min(len(clean), start + max_chars)
        chunks.append(clean[start:end])
        if end >= len(clean):
            break
        start += step
    return chunks


def chunk_text(
    text: str,
    *,
    language: str,
    query_id: str,
    passage_id: str,
    max_chars: int = 700,
    overlap: int = 100,
    strategy: str = "sentence_overlap",
) -> list[Chunk]:
    clean = normalize_text(text)
    if not clean:
        return []
    if strategy == "fixed_overlap":
        chunks = _fixed_chunks(clean, max_chars, overlap)
    elif strategy in {"sentence_overlap", "semantic"}:
        chunks = _sentence_chunks(clean, max_chars, overlap)
    else:
        raise ValueError(f"unknown chunk strategy: {strategy}")
    return [
        Chunk(
            id=content_hash(passage_id, str(index), chunk),
            text=chunk,
            language=language,
            query_id=query_id,
            selected=False,
            strategy=strategy,
            metadata={"passage_id": passage_id, "chunk_index": str(index)},
        )
        for index, chunk in enumerate(chunks)
    ]
