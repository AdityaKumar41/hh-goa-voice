import re
from dataclasses import dataclass
from typing import ClassVar

from .core import normalize_text
from .schemas import Citation


@dataclass(frozen=True)
class SearchDocument:
    id: str
    text: str
    language: str
    score: float
    selected: bool = False
    source_type: str = "dataset"
    source_title: str | None = None


class InMemoryRetriever:
    """Deterministic development retriever; production uses QdrantRetriever."""

    stop_words: ClassVar[set[str]] = {
        "a",
        "an",
        "are",
        "about",
        "do",
        "for",
        "how",
        "in",
        "is",
        "of",
        "on",
        "the",
        "to",
        "what",
        "where",
        "who",
        "why",
    }

    def __init__(self, documents: list[SearchDocument] | None = None):
        self.documents = documents or []

    async def search(self, query: str, language: str, top_k: int) -> list[Citation]:
        terms = {
            term
            for term in re.findall(r"\w+", normalize_text(query).lower())
            if term not in self.stop_words
        }
        scored = []
        for document in self.documents:
            if document.language not in {language, "en"} and language != "en":
                continue
            words = set(re.findall(r"\w+", normalize_text(document.text).lower()))
            overlap = len(terms & words) / max(1, len(terms))
            # Development documents must not masquerade as evidence for an
            # unrelated query. The stored score is a relevance prior, not a
            # license to return the document when lexical overlap is zero.
            if overlap > 0:
                score = max(document.score, overlap)
                scored.append((score, document))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            Citation(
                passage_id=doc.id,
                language=doc.language,
                text=doc.text,
                score=round(score, 4),
                selected=doc.selected,
                source_type=doc.source_type,
                source_title=doc.source_title,
            )
            for score, doc in scored[:top_k]
        ]


class QdrantRetriever:
    def __init__(self, client, collection: str, embedder):
        self.client, self.collection, self.embedder = client, collection, embedder

    async def search_dense(self, query: str, language: str, top_k: int) -> list[Citation]:
        vector = await self.embedder.embed(query)
        query_filter = {
            "should": [
                {"key": "language", "match": {"value": language}},
                {"key": "language", "match": {"value": "en"}},
            ]
        }
        hits = self.client.query_points(
            collection_name=self.collection, query=vector, query_filter=query_filter, limit=top_k
        ).points
        return [
            Citation(
                passage_id=str(hit.id),
                language=hit.payload["language"],
                text=hit.payload["text"],
                score=float(hit.score),
                selected=bool(hit.payload.get("selected", False)),
                source_type=hit.payload.get("source_type", "dataset"),
                source_title=hit.payload.get("source_title") or None,
            )
            for hit in hits
        ]

    async def search_lexical(self, query: str, language: str, top_k: int) -> list[Citation]:
        from qdrant_client.models import FieldCondition, Filter, MatchText, MatchValue

        points, _ = self.client.scroll(
            collection_name=self.collection,
            scroll_filter=Filter(
                must=[
                    FieldCondition(key="text", match=MatchText(text=query)),
                    FieldCondition(key="language", match=MatchValue(value=language)),
                ]
            ),
            limit=top_k,
            with_payload=True,
            with_vectors=False,
        )
        return [
            Citation(
                passage_id=str(point.id),
                language=point.payload["language"],
                text=point.payload["text"],
                score=1.0,
                selected=bool(point.payload.get("selected", False)),
                source_type=point.payload.get("source_type", "dataset"),
                source_title=point.payload.get("source_title") or None,
            )
            for point in points
        ]

    async def search(self, query: str, language: str, top_k: int) -> list[Citation]:
        return await HybridRetriever(self).search(query, language, top_k)


class HybridRetriever:
    """Merge dense and lexical candidates while preserving dense relevance scores."""

    def __init__(self, dense_retriever, lexical_retriever=None):
        self.dense_retriever = dense_retriever
        self.lexical_retriever = lexical_retriever or dense_retriever

    async def search(self, query: str, language: str, top_k: int) -> list[Citation]:
        dense = await self.dense_retriever.search_dense(query, language, top_k)
        lexical = await self.lexical_retriever.search_lexical(query, language, top_k)
        merged: dict[str, tuple[Citation, float]] = {}
        for rank, citation in enumerate(dense):
            merged[citation.passage_id] = (citation, 1 / (60 + rank + 1))
        for rank, citation in enumerate(lexical):
            if citation.passage_id in merged:
                existing, score = merged[citation.passage_id]
                merged[citation.passage_id] = (existing, score + 1 / (60 + rank + 1))
            else:
                merged[citation.passage_id] = (citation, 1 / (60 + rank + 1))
        ranked = sorted(merged.values(), key=lambda item: item[1], reverse=True)
        return [citation for citation, _ in ranked[:top_k]]


def grounded(citations: list[Citation], minimum: float) -> bool:
    return bool(citations and max(citation.score for citation in citations) >= minimum)
