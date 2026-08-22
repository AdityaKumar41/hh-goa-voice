"""Qdrant indexing interfaces used by the offline worker."""

import itertools
import logging
import math
from collections.abc import Callable
from dataclasses import asdict

from .core import Chunk, _split_sentences, chunk_text, content_hash, normalize_text

logger = logging.getLogger(__name__)


def cosine_similarity(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    return dot / max(1e-9, math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right)))


def chunk_semantic(
    text: str,
    *,
    language: str,
    query_id: str,
    passage_id: str,
    embed: Callable[[list[str]], list[list[float]]],
    max_chars: int = 700,
    overlap: int = 100,
    similarity_threshold: float = 0.42,
) -> list[Chunk]:
    """Embedding-aware chunking: break on semantic coherence drops between sentences.

    Merges sentences while their embeddings stay similar and the window is under
    ``max_chars``; a large drop in similarity starts a new boundary. Produces chunks
    labelled ``semantic`` alongside the deterministic sentence/fixed strategies.
    """
    clean = normalize_text(text)
    if not clean or len(clean) <= max_chars:
        return chunk_text(
            clean,
            language=language,
            query_id=query_id,
            passage_id=passage_id,
            strategy="semantic",
        )
    sentences = _split_sentences(clean) or [clean]
    if len(sentences) == 1:
        return chunk_text(
            clean,
            language=language,
            query_id=query_id,
            passage_id=passage_id,
            strategy="semantic",
        )
    vectors = embed(sentences)
    boundaries: list[int] = [0]
    current = sentences[0]
    for index in range(1, len(sentences)):
        similarity = cosine_similarity(vectors[index - 1], vectors[index])
        candidate = f"{current} {sentences[index]}"
        if len(candidate) > max_chars or similarity < similarity_threshold:
            boundaries.append(index)
            current = sentences[index]
        else:
            current = candidate
    if boundaries[-1] != len(sentences):
        boundaries.append(len(sentences))
    pieces = [
        " ".join(sentences[start:end])
        for start, end in itertools.pairwise(boundaries)
    ]
    merged: list[str] = []
    for piece in pieces:
        if merged and len(piece) < overlap:
            merged[-1] = f"{merged[-1]} {piece}"
        else:
            merged.append(piece)
    return [
        Chunk(
            id=content_hash("semantic", passage_id, str(index), chunk),
            text=chunk,
            language=language,
            query_id=query_id,
            selected=False,
            strategy="semantic",
            metadata={"passage_id": passage_id, "chunk_index": str(index)},
        )
        for index, chunk in enumerate(merged)
    ]


class Embedder:
    """Sentence embedder with retrieval-friendly prefixing for e5-style models.

    ``intfloat/multilingual-e5-*`` models expect ``query: `` / ``passage: `` prefixes;
    the encoder adds them automatically so callers never need to know the model family.
    """

    def __init__(self, model_name: str, device: str | None = None):
        from .config import get_settings

        self.model_name = model_name
        self._model = None
        self._device = device or get_settings().embed_device
        is_e5 = "e5" in model_name.lower()
        self._query_prefix = "query: " if is_e5 else ""
        self._passage_prefix = "passage: " if is_e5 else ""

    def _load(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise RuntimeError("Install sentence-transformers for vector indexing") from exc
            self._model = SentenceTransformer(self.model_name, device=self._device)
        return self._model

    async def embed(self, text: str) -> list[float]:
        return (
            self._load()
            .encode(f"{self._query_prefix}{text}", normalize_embeddings=True)
            .tolist()
        )

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        prefixed = [f"{self._passage_prefix}{text}" for text in texts]
        return self._load().encode(prefixed, normalize_embeddings=True).tolist()

    @property
    def dimension(self) -> int:
        dimension = self._load().get_sentence_embedding_dimension()
        if not dimension:
            raise RuntimeError(f"embedding model returned no dimension: {self.model_name}")
        return int(dimension)


class QdrantIndexer:
    def __init__(self, client, collection: str, embedder: Embedder, vector_size: int | None = None):
        self.client, self.collection, self.embedder, self.vector_size = (
            client,
            collection,
            embedder,
            vector_size or embedder.dimension,
        )

    def ensure_collection(self) -> None:
        from qdrant_client.models import (
            Distance,
            PayloadSchemaType,
            TextIndexParams,
            TokenizerType,
            VectorParams,
        )

        collections = {item.name for item in self.client.get_collections().collections}
        if self.collection not in collections:
            self.client.create_collection(
                self.collection,
                vectors_config=VectorParams(size=self.vector_size, distance=Distance.COSINE),
            )
        for field in ("language", "selected", "strategy"):
            try:
                self.client.create_payload_index(
                    self.collection, field_name=field, field_schema=PayloadSchemaType.KEYWORD
                )
            except Exception:
                logger.debug("payload index already exists or is unavailable", exc_info=True)
        try:
            self.client.create_payload_index(
                self.collection,
                field_name="text",
                field_schema=TextIndexParams(
                    type="text", tokenizer=TokenizerType.WORD, lowercase=True
                ),
            )
        except Exception:
            logger.debug("text payload index already exists or is unavailable", exc_info=True)

    def upsert(self, chunks: list[Chunk]) -> int:
        from qdrant_client.models import PointStruct

        vectors = self.embedder.embed_batch([chunk.text for chunk in chunks])
        points = [
            PointStruct(
                id=chunk.id[:32],
                vector=vector,
                payload={**asdict(chunk), **chunk.metadata, "metadata": chunk.metadata},
            )
            for chunk, vector in zip(chunks, vectors)
        ]
        self.client.upsert(collection_name=self.collection, points=points, wait=True)
        return len(points)

    def point_count(self) -> int:
        return int(self.client.count(collection_name=self.collection, exact=True).count)

    def language_coverage(self) -> set[str]:
        languages: set[str] = set()
        offset = None
        while True:
            points, offset = self.client.scroll(
                collection_name=self.collection,
                limit=256,
                offset=offset,
                with_payload=["language"],
                with_vectors=False,
            )
            languages.update(
                str(point.payload.get("language"))
                for point in points
                if point.payload and point.payload.get("language")
            )
            if offset is None:
                return languages

    def promote(self, alias: str) -> None:
        from qdrant_client.models import (
            CreateAlias,
            CreateAliasOperation,
            DeleteAlias,
            DeleteAliasOperation,
        )

        aliases = self.client.get_collection_aliases(collection_name=self.collection).aliases
        operations = [
            DeleteAliasOperation(delete_alias=DeleteAlias(alias_name=item.alias_name))
            for item in aliases
            if item.alias_name == alias
        ]
        operations.append(
            CreateAliasOperation(
                create_alias=CreateAlias(collection_name=self.collection, alias_name=alias)
            )
        )
        self.client.update_collection_aliases(operations)
