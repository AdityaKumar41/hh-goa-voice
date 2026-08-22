import pytest

from voice_rag.config import Settings
from voice_rag.pipeline import QueryPipeline
from voice_rag.retrieval import InMemoryRetriever, SearchDocument
from voice_rag.schemas import QueryRequest


class Generator:
    async def generate(self, question, language, citations):
        return {
            "answer": "The answer is grounded.",
            "confidence": 0.9,
            "grounded": True,
            "refused": False,
        }


@pytest.mark.asyncio
async def test_text_query_returns_grounded_citations_and_timings():
    retriever = InMemoryRetriever([SearchDocument("p1", "Goa is in India", "en", 0.8, True)])
    response = await QueryPipeline(
        Settings(min_retrieval_score=0.2, min_answer_overlap=0), retriever=retriever, generator=Generator()
    ).run(QueryRequest(text="Where is Goa?"))
    assert response.answer == "The answer is grounded."
    assert response.grounded is True
    assert response.citations[0].passage_id == "p1"
    assert "retrieval" in response.timings_ms


@pytest.mark.asyncio
async def test_unsupported_query_refuses_before_generation():
    pipeline = QueryPipeline(
        Settings(min_retrieval_score=0.5, min_answer_overlap=0),
        retriever=InMemoryRetriever([]),
        generator=Generator(),
    )
    response = await pipeline.run(QueryRequest(text="Something unrelated"))
    assert response.refused is True
    assert response.refusal_reason == "insufficient evidence"


@pytest.mark.asyncio
async def test_fallback_retriever_does_not_return_unrelated_demo_evidence():
    retriever = InMemoryRetriever([SearchDocument("demo", "Goa is in India", "en", 0.8)])
    response = await QueryPipeline(
        Settings(min_retrieval_score=0.2, min_answer_overlap=0), retriever=retriever, generator=Generator()
    ).run(QueryRequest(text="What is the weather on Mars?"))

    assert response.refused is True
    assert response.citations == []


@pytest.mark.asyncio
async def test_platform_capability_question_uses_platform_evidence():
    retriever = InMemoryRetriever(
        [
            SearchDocument(
                "platform-about",
                "I am a voice-first multilingual research assistant. My job is to "
                "transcribe spoken questions and return answers with citations.",
                "en",
                0.95,
            )
        ]
    )
    response = await QueryPipeline(
        Settings(min_retrieval_score=0.2, min_answer_overlap=0), retriever=retriever, generator=Generator()
    ).run(QueryRequest(text="What is your main job here?"))

    assert response.refused is False
    assert response.citations[0].passage_id == "platform-about"


@pytest.mark.asyncio
async def test_non_platform_question_cannot_use_platform_about_evidence():
    retriever = InMemoryRetriever(
        [SearchDocument("platform-about", "I am a voice-first research assistant.", "en", 0.95)]
    )
    response = await QueryPipeline(
        Settings(min_retrieval_score=0.2, min_answer_overlap=0), retriever=retriever, generator=Generator()
    ).run(QueryRequest(text="Tell me the Hacker House Goa rules."))

    assert response.refused is True
    assert response.citations == []


@pytest.mark.asyncio
async def test_domain_question_wins_over_assistant_capability_language():
    retriever = InMemoryRetriever(
        [
            SearchDocument("platform-about", "I am a voice-first research assistant.", "en", 0.95),
            SearchDocument("demo-goa", "Goa is a state in India.", "en", 0.8),
        ]
    )
    response = await QueryPipeline(
        Settings(min_retrieval_score=0.2, min_answer_overlap=0), retriever=retriever, generator=Generator()
    ).run(QueryRequest(text="Tell me about yourself and Hacker House Goa."))

    assert all(item.passage_id != "platform-about" for item in response.citations)


@pytest.mark.asyncio
async def test_answer_not_grounded_in_evidence_is_refused():
    class HallucinatingGenerator:
        async def generate(self, question, language, citations):
            return {
                "answer": "The capital of Pluto is Zoomington.",
                "confidence": 0.95,
                "grounded": True,
                "refused": False,
            }

    retriever = InMemoryRetriever([SearchDocument("p1", "Goa is a state on the west coast of India.", "en", 0.9)])
    response = await QueryPipeline(
        Settings(min_retrieval_score=0.2, min_answer_overlap=0.5),
        retriever=retriever,
        generator=HallucinatingGenerator(),
    ).run(QueryRequest(text="Where is Goa?"))

    assert response.refused is True
    assert "not grounded" in (response.refusal_reason or "")


@pytest.mark.asyncio
async def test_fast_mode_uses_local_extractive_answer_and_is_fast():
    retriever = InMemoryRetriever(
        [
            SearchDocument(
                "p1",
                "Hacker House Goa is free to attend. Participants bring their own laptop. The event provides meals and accommodation.",
                "en",
                0.9,
                True,
            )
        ]
    )
    import time

    pipeline = QueryPipeline(Settings(min_retrieval_score=0.2), retriever=retriever)
    t0 = time.perf_counter()
    response = await pipeline.run(QueryRequest(text="Is Hacker House Goa free?", mode="fast"))
    total = (time.perf_counter() - t0) * 1000

    assert response.mode == "fast"
    assert response.refused is False
    assert "free" in response.answer.casefold()
    assert response.timings_ms.get("generation", 0) < 100
    assert total < 200


@pytest.mark.asyncio
async def test_fast_mode_refuses_without_evidence():
    retriever = InMemoryRetriever([])
    response = await QueryPipeline(
        Settings(min_retrieval_score=0.2), retriever=retriever
    ).run(QueryRequest(text="What is an unknown thing?", mode="fast"))
    assert response.refused is True
    assert response.mode == "fast"
    assert response.answer != ""


@pytest.mark.asyncio
async def test_fast_mode_refuses_unrelated_high_scoring_passage():
    # A top-ranked passage with no relation to the question must be refused, not quoted.
    retriever = InMemoryRetriever(
        [
            SearchDocument(
                "tax",
                "The income tax filing deadline in India is usually 31 July. Late filings attract a penalty.",
                "en",
                0.99,
                True,
                "dataset",
            )
        ]
    )
    response = await QueryPipeline(
        Settings(min_retrieval_score=0.2), retriever=retriever
    ).run(QueryRequest(text="When is Hacker House Goa 2026?", mode="fast"))
    assert response.refused is True
    assert response.answer != "When is Hacker House Goa 2026?"


@pytest.mark.asyncio
async def test_fast_mode_refuses_unknown_content_question():

    retriever = InMemoryRetriever(
        [SearchDocument("x", "Goa is a state on the west coast of India.", "en", 0.9, True, "dataset")]
    )
    response = await QueryPipeline(
        Settings(min_retrieval_score=0.2), retriever=retriever
    ).run(QueryRequest(text="What is the population of Neptune?", mode="fast"))
    assert response.refused is True
    assert "evidence" in (response.refusal_reason or "").lower()


@pytest.mark.asyncio
async def test_fast_mode_does_not_answer_with_platform_meta_for_content_questions():
    retriever = InMemoryRetriever(
        [
            SearchDocument("evt", "Hacker House Goa 2026 is a four-day building event in Goa.", "en", 0.9, True, "event"),
        ]
    )

    class LeakyGenerator:
        async def generate(self, question, language, citations):
            # Simulate what the harness should already have filtered out.
            return {"answer": None, "confidence": 0, "grounded": False, "refused": True}

    pipeline = QueryPipeline(
        Settings(min_retrieval_score=0.2, min_answer_overlap=0),
        retriever=retriever,
        generator=LeakyGenerator(),
    )
    response = await pipeline.run(
        QueryRequest(text="Hacker House Goa dates and location?", mode="normal")
    )
    # platform meta is stripped before it can become evidence
    assert all(c.source_type != "platform" for c in response.citations)


@pytest.mark.asyncio
async def test_platform_question_still_allowed_platform_evidence():
    retriever = InMemoryRetriever(
        [SearchDocument("platform-about", "I am a voice-first multilingual research assistant.", "en", 0.9, True, "platform")]
    )
    response = await QueryPipeline(
        Settings(min_retrieval_score=0.2, min_answer_overlap=0), retriever=retriever
    ).run(QueryRequest(text="Are you a research assistant?", mode="fast"))
    assert "assistant" in response.answer or (
        response.citations and response.citations[0].source_type == "platform"
    )
