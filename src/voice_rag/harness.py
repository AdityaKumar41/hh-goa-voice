import re
import time
import uuid
from collections.abc import Awaitable, Callable

from .config import Settings
from .core import detect_language, normalize_text
from .guards import QueryGuard, answer_overlap_ratio
from .metadata import QueryTraceStore
from .observability import TraceSink, privacy_id
from .providers import (
    AnswerGenerator,
    LocalFastAnswerGenerator,
    SpeechToText,
    decode_audio,
)
from .retrieval import InMemoryRetriever, grounded
from .schemas import Citation, QueryRequest, QueryResponse
from .tools import ReadOnlyWebTool


class ResearchHarness:
    """The platform seam for centrally improving every user's research turn."""

    def __init__(
        self,
        settings: Settings,
        retriever=None,
        stt=None,
        generator=None,
        traces=None,
        web_tool=None,
        trace_db=None,
    ):
        self.settings = settings
        self.retriever = retriever or InMemoryRetriever()
        self.stt = stt or SpeechToText(settings)
        self.generator = generator or AnswerGenerator(settings)
        self.fast_generator = LocalFastAnswerGenerator(settings)
        self.guard = QueryGuard()
        self.traces = traces or TraceSink(settings.trace_path)
        self.web_tool = web_tool or ReadOnlyWebTool(settings)
        self.trace_db = trace_db or QueryTraceStore(settings.postgres_dsn)

    def _active_generator(self, mode: str | None):
        """Route to the hosted LLM (normal) or the local extractive path (fast)."""
        if mode is None:
            mode = self.settings.answer_mode
        return self.fast_generator if mode == "fast" else self.generator

    async def run(
        self,
        request: QueryRequest,
        user_id: str = "anonymous",
        on_event: Callable[[str, dict], None] | None = None,
        on_token: Callable[[str], Awaitable[None]] | None = None,
    ) -> QueryResponse:
        def event(name: str, **data) -> None:
            self.traces.emit(name, trace_id, **data)
            if on_event:
                on_event(name, data)

        trace_id = uuid.uuid4().hex
        started = time.perf_counter()
        timings: dict[str, float] = {}
        event(
            "run.started",
            user_id=privacy_id(user_id),
            model=self.settings.opencode_model,
            prompt_version=self.settings.prompt_version,
            index_version=self.settings.index_version,
        )
        self.traces.emit("harness_start", trace_id, user_id=privacy_id(user_id))
        transcript = request.text or ""
        if request.audio_base64:
            stage = time.perf_counter()
            transcript = await self.stt.transcribe(
                decode_audio(request.audio_base64), request.language
            )
            timings["speech_to_text"] = (time.perf_counter() - stage) * 1000
            event("transcript.ready", stage="speech_to_text", duration_ms=timings["speech_to_text"])
        transcript = normalize_text(transcript)
        if not transcript:
            raise ValueError("text or audio_base64 is required")
        decision = self.guard.check(transcript)
        if not decision.allowed:
            return self._refusal(
                trace_id,
                transcript,
                request.language or "en",
                decision.reason or "blocked",
                decision.category,
                timings,
                started,
                mode=getattr(request, "mode", None),
            )
        language = detect_language(transcript, request.language)
        self.traces.emit("retrieval_gate", trace_id, decision="retrieve", language=language)
        event("transcript.ready", transcript=transcript, language=language)
        event("retrieval.started", language=language)
        stage = time.perf_counter()
        if request.source_url:
            document = await self.web_tool.read(request.source_url)
            citations = [
                Citation(
                    passage_id=f"web:{document.provider}:{document.url}",
                    language=language,
                    text=document.text,
                    score=1.0,
                    selected=True,
                    source_type="web",
                    source_title=document.title,
                )
            ]
        else:
            citations = await self.retriever.search(
                transcript, language, self.settings.retrieval_top_k
            )
        timings["retrieval"] = (time.perf_counter() - stage) * 1000
        event(
            "retrieval.completed",
            stage="retrieval",
            duration_ms=timings["retrieval"],
            result_count=len(citations),
        )
        if not self._is_platform_question(transcript):
            # Platform meta ("about the assistant") must never serve as evidence for a
            # normal research question. Match on source_type, because Qdrant chunks carry
            # a content-hash id, not the curated row's original id.
            citations = [item for item in citations if item.source_type != "platform"]
        citations = self._fit_context(citations)
        if not grounded(citations, self.settings.min_retrieval_score) and hasattr(self.web_tool, "search"):
            web_documents = await self.web_tool.search(transcript)
            citations.extend(
                Citation(
                    passage_id=f"web:{document.provider}:{document.url}",
                    language=language,
                    text=document.text,
                    score=0.55,
                    selected=True,
                    source_type="web",
                    source_title=document.title,
                )
                for document in web_documents
            )
        if not grounded(citations, self.settings.min_retrieval_score):
            return self._refusal(
                trace_id,
                transcript,
                language,
                "insufficient evidence",
                "ungrounded",
                timings,
                started,
                citations,
                mode=getattr(request, "mode", None),
            )
        event("generation.started", citation_count=len(citations))
        stage = time.perf_counter()
        generator = self._active_generator(getattr(request, "mode", None))
        if on_token and hasattr(generator, "generate_stream"):
            result = await generator.generate_stream(
                transcript, language, citations, on_token
            )
        else:
            result = await generator.generate(transcript, language, citations)
        timings["generation"] = (time.perf_counter() - stage) * 1000
        timings["total"] = (time.perf_counter() - started) * 1000
        refused = bool(result.get("refused", False))
        raw_answer = result.get("answer")
        answer = (
            str(raw_answer).strip()
            if raw_answer is not None and str(raw_answer).strip()
            else (
                "I could not find enough evidence in the research collection to answer that."
                if refused
                else "I could not produce a grounded answer."
            )
        )
        if len(answer) > self.settings.max_answer_chars:
            clipped = answer[: self.settings.max_answer_chars].rsplit(" ", 1)[0]
            answer = clipped.rstrip(" .,;:") + "…"
        refusal_reason = result.get("refusal_reason")
        citation_ids = result.get("citation_ids")
        if citation_ids:
            valid_ids = {item.passage_id for item in citations}
            if not set(map(str, citation_ids)).intersection(valid_ids):
                refused = True
                refusal_reason = "The answer provider did not cite retrieved evidence."
        if not bool(result.get("grounded", True)):
            refused = True
            refusal_reason = refusal_reason or "The generated answer failed grounding validation."
        if not refused:
            overlap = answer_overlap_ratio(
                answer, [item.text for item in citations]
            )
            if overlap < self.settings.min_answer_overlap:
                refused = True
                refusal_reason = "The generated answer was not grounded in the retrieved evidence."
                answer = "I could not produce an answer that is supported by the retrieved evidence."
        if refused and not refusal_reason:
            refusal_reason = "The retrieved evidence was not sufficient to support an answer."
        response = QueryResponse(
            trace_id=trace_id,
            transcript=transcript,
            detected_language=language,
            answer=answer,
            confidence=max(0, min(1, float(result.get("confidence", 0)))),
            grounded=bool(result.get("grounded", True)),
            refused=refused,
            refusal_reason=refusal_reason,
            citations=citations,
            timings_ms=timings,
            mode=result.get("mode", getattr(request, "mode", None) or self.settings.answer_mode),
        )
        event(
            "answer.completed",
            answer=response.answer,
            grounded=response.grounded,
            refused=response.refused,
        )
        event(
            "run.completed",
            response=response.model_dump(),
            grounded=response.grounded,
            refused=response.refused,
            timings_ms=timings,
        )
        self.traces.emit("harness_end", trace_id, grounded=response.grounded, refused=response.refused)
        self.trace_db.write(
            trace_id,
            language=language,
            transcript=transcript,
            grounded=response.grounded,
            refused=response.refused,
            timings_ms=timings,
        )
        return response

    def _fit_context(self, citations: list[Citation]) -> list[Citation]:
        selected: list[Citation] = []
        seen: set[str] = set()
        used = 0
        for citation in citations:
            key = normalize_text(citation.text).casefold()
            if not key or key in seen:
                continue
            if selected and used + len(citation.text) > self.settings.max_context_chars:
                break
            seen.add(key)
            selected.append(citation)
            used += len(citation.text)
        return selected

    @staticmethod
    def _is_platform_question(text: str) -> bool:
        terms = set(re.findall(r"\w+", text.casefold()))
        domain_terms = {"hacker", "house", "goa", "dataset", "rules", "event"}
        if terms & domain_terms:
            return False
        capability_terms = {
            "assistant",
            "capability",
            "capabilities",
            "do",
            "help",
            "job",
            "purpose",
            "role",
            "work",
            "your",
            "yourself",
            "you",
        }
        return bool(terms & capability_terms)

    def _refusal(
        self, trace_id, transcript, language, reason, category, timings, started, citations=None, mode=None
    ):
        timings["total"] = (time.perf_counter() - started) * 1000
        response = QueryResponse(
            trace_id=trace_id,
            transcript=transcript,
            detected_language=language,
            answer="I cannot answer that request safely or with sufficient evidence.",
            confidence=0,
            grounded=False,
            refused=True,
            refusal_reason=reason,
            citations=citations or [],
            timings_ms=timings,
            mode=mode or self.settings.answer_mode,
        )
        self.traces.emit(
            "harness_end",
            trace_id,
            grounded=False,
            refused=True,
            refusal_category=category,
            timings_ms=timings,
        )
        self.trace_db.write(
            trace_id,
            language=language,
            transcript=transcript,
            grounded=False,
            refused=True,
            timings_ms=timings,
        )
        return response
