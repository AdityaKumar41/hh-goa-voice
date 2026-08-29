import asyncio
import base64
import json
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from .config import Settings
from .guards import answer_overlap_ratio
from .schemas import Citation

RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


def _normalize_spaces(value: str) -> str:
    return " ".join(str(value).split())


class ProviderError(RuntimeError):
    pass


class RetryableProviderError(ProviderError):
    pass


class LocalFastAnswerGenerator:
    """Deterministic, on-device extractive answer generator for the <200ms fast mode.

    Retrieval-first extractive QA: pick the passage that is both high-scoring and
    lexically relevant to the question, return it as a compact quoted span. No hosted
    LLM and no network call, so the whole route-to-answer fits under 200ms. Behaves like
    a proper harness: refuses when evidence is missing, weak, or unrelated to the
    question, and never cites evidence it did not use.
    """

    def __init__(self, settings=None):
        from .config import get_settings

        self.settings = settings or get_settings()

    async def generate(
        self, question: str, language: str, citations: list[Citation]
    ) -> dict[str, Any]:
        return self._extract(question, language, citations)

    async def generate_stream(
        self,
        question: str,
        language: str,
        citations: list[Citation],
        on_token: Callable[[str], Awaitable[None]],
    ) -> dict[str, Any]:
        result = self._extract(question, language, citations)
        answer = str(result["answer"])
        # Emit in a few chunks so the UI still shows a streaming feel.
        for index in range(0, len(answer), 40):
            await on_token(answer[index : index + 40])
        return result

    def _refusal(self, reason: str) -> dict[str, Any]:
        return {
            "answer": None,
            "confidence": 0.0,
            "grounded": False,
            "refused": True,
            "refusal_reason": reason,
            "mode": "fast",
        }

    def _extract(self, question: str, language: str, citations: list[Citation]) -> dict[str, Any]:
        if not citations:
            return self._refusal("No evidence was retrieved.")
        import re as _re

        def relevance(citation: Citation) -> float:
            return answer_overlap_ratio(question, [citation.text])

        def lead_match(citation: Citation) -> bool:
            """True when the passage's first sentence contains the question verbatim.

            QA rows echo the exact question ("What is Hacker House Goa? Hacker House Goa
            is ..."); boosting that lead stops a sibling QA row with the same trailing
            phrase (e.g. a hashtag row) from winning purely on dense score.
            """
            question_norm = _normalize_spaces(question).casefold()
            first = citation.text.split("?", 1)[0] + "?"
            return question_norm in _normalize_spaces(first).casefold()

        # Rank by: does the passage relate to the question, is its lead the exact
        # question (echo), is it the marked/gold answer, then retrieval score. Platform
        # meta ("about the assistant") is de-prioritised so it never answers a content question.
        ranked = sorted(
            citations,
            key=lambda item: (
                relevance(item),
                lead_match(item),
                item.selected,
                item.source_type != "platform",
                item.score,
            ),
            reverse=True,
        )
        best = ranked[0]
        score = max(0.0, float(best.score))
        text = best.text.strip()
        if not text:
            return self._refusal("The best passage was empty.")

        # Guardrail: only quote a passage that is clearly on-topic. Hard floors:
#   - any passage must share at least 40% of the question's content words;
#   - dataset chunks (arbitrary web text) additionally need the strict 60% overlap;
#   - curated facts are trusted, so a moderate overlap is acceptable only when the
#     dense match is high-confidence (>= 0.85) — otherwise a merely-"India"-related
#     curated row could answer a different question.
# A cross-script (Indic) query can still match a curated fact through the multilingual
# embedder at high confidence. Anything weaker is refused, never answered with unrelated text.
        relevance_score = relevance(best)
        indic_question = any("\u0900" <= ch <= "\u0d7f" for ch in question)
        curated = best.source_type in {"event", "platform"}
        weak = (
        relevance_score < 0.40
        or (relevance_score < self.settings.fast_relevance_threshold and score < (0.85 if curated else 9.0))
        )
        if weak and not (indic_question and curated and score >= 0.80):
            return self._refusal(
                "The retrieved evidence did not contain information about this question."
            )

        # Compact span: the answer-bearing sentences, up to ~240 chars. A qa_pair
        # chunk has the form "<question>? <answer>." — drop the echoed question sentence
        # so the answer reads naturally instead of parroting the user's own question.
        sentences = _re.split(r"(?<=[.!?।॥])\s+", text)
        if sentences and sentences[0].rstrip().endswith("?"):
            sentences = sentences[1:]
        span = ""
        for sentence in sentences:
            if len(span) + len(sentence) + 1 > 240:
                break
            span = f"{span} {sentence}".strip()
        answers = [part for part in (span, text) if part and len(part) >= 12]
        answer = answers[0] if answers else text
        return {
            "answer": answer,
            "confidence": round(min(1.0, 0.5 + 0.4 * score + 0.2 * relevance_score), 3),
            "grounded": True,
            "refused": False,
            "refusal_reason": None,
            "citation_ids": [best.passage_id],
            "mode": "fast",
            "extractive": True,
        }


async def retry_async(
    fn: Callable[[], Awaitable[Any]],
    *,
    attempts: int = 3,
    base_delay: float = 0.4,
    max_delay: float = 5.0,
) -> Any:
    """Exponential backoff with jitter for transient provider failures."""
    delay = base_delay
    for attempt in range(attempts):
        try:
            return await fn()
        except (httpx.TransportError, RetryableProviderError):
            if attempt == attempts - 1:
                raise
            delay = min(delay * 2, max_delay) + random.uniform(0, 0.25)
            await asyncio.sleep(delay)


class CircuitBreaker:
    """Per-provider failure breaker: open after N consecutive failures, half-open on cooldown."""

    def __init__(self, failure_threshold: int = 3, cooldown_seconds: float = 30.0):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._failures = 0
        self._opened_at = 0.0
        self._lock = asyncio.Lock()

    @property
    def open(self) -> bool:
        return self._failures >= self.failure_threshold

    async def call(self, fn: Callable[..., Awaitable[Any]], *args: Any, **kwargs: Any) -> Any:
        async with self._lock:
            if self.open:
                if time.time() - self._opened_at < self.cooldown_seconds:
                    raise ProviderError(
                        "provider circuit breaker is open after repeated failures; retrying later"
                    )
                self._failures = 0
        try:
            result = await fn(*args, **kwargs)
        except Exception:
            async with self._lock:
                self._failures += 1
                if self.open:
                    self._opened_at = time.time()
            raise
        async with self._lock:
            self._failures = 0
        return result


class SpeechToText:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._breaker = CircuitBreaker()

    async def transcribe(self, audio: bytes, language: str | None = None) -> str:
        if not self.settings.elevenlabs_api_key:
            raise ProviderError("ELEVENLABS_API_KEY is not configured")
        if len(audio) > self.settings.max_audio_bytes:
            raise ProviderError("audio exceeds configured size limit")
        return await self._breaker.call(self._transcribe_once, audio, language)

    async def _transcribe_once(self, audio: bytes, language: str | None) -> str:
        headers = {"xi-api-key": self.settings.elevenlabs_api_key}
        files = {"file": ("recording.webm", audio, "audio/webm")}
        data = {"model_id": self.settings.elevenlabs_stt_model}
        if language:
            data["language_code"] = language

        async def attempt() -> httpx.Response:
            async with httpx.AsyncClient(
                timeout=self.settings.request_timeout_seconds
            ) as client:
                response = await client.post(
                    self.settings.elevenlabs_stt_url, headers=headers, files=files, data=data
                )
            if response.status_code in RETRYABLE_STATUS:
                raise RetryableProviderError(f"speech provider returned {response.status_code}")
            return response

        response = await retry_async(attempt)
        if response.is_error:
            raise ProviderError(f"speech provider returned {response.status_code}")
        payload = response.json()
        transcript = payload.get("text") or payload.get("transcript")
        if not transcript:
            raise ProviderError("speech provider returned no transcript")
        return transcript


class AnswerGenerator:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._breaker = CircuitBreaker()

    async def generate(
        self, question: str, language: str, citations: list[Citation]
    ) -> dict[str, Any]:
        api_key = self.opencode_api_key()
        return await self._breaker.call(
            self._generate_once, question, language, citations, api_key
        )

    async def _generate_once(
        self,
        question: str,
        language: str,
        citations: list[Citation],
        api_key: str,
    ) -> dict[str, Any]:
        body = self._body(question, language, citations)
        headers = {"Authorization": f"Bearer {api_key}"}
        base_url = self.settings.opencode_go_base_url or self.settings.opencode_base_url

        async def attempt() -> httpx.Response:
            async with httpx.AsyncClient(
                timeout=self.settings.request_timeout_seconds
            ) as client:
                response = await client.post(
                    f"{base_url.rstrip('/')}/chat/completions",
                    headers=headers,
                    json=body,
                )
            if response.status_code in RETRYABLE_STATUS:
                raise RetryableProviderError(f"answer provider returned {response.status_code}")
            return response

        response = await retry_async(attempt)
        return self._parse_response(response)

    def _body(self, question: str, language: str, citations: list[Citation]) -> dict:
        context = "\n\n".join(f"[{item.passage_id}] {item.text}" for item in citations)
        system = (
            "You are a grounded research assistant. Answer ONLY from the CONTEXT passages. "
            "Never use your own knowledge or state facts that are not in CONTEXT. Cite the "
            "passage you used as [ID]. "
            "If CONTEXT does not contain the answer, set refused=true with a one-line "
            "refusal_reason. "
            "Reply in the user's LANGUAGE. Do not describe yourself, your capabilities, or "
            "that you are an assistant/AI. Be concise (under 90 words). "
            "Return strict JSON with keys: answer, confidence (0..1), grounded, refused, "
            "refusal_reason, citation_ids."
        )
        return {
            "model": self.settings.opencode_model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": f"LANGUAGE: {language}\nQUESTION: {question}\nCONTEXT:\n{context}",
                },
            ],
        }

    async def generate_stream(
        self,
        question: str,
        language: str,
        citations: list[Citation],
        on_token: Callable[[str], Awaitable[None]],
    ) -> dict[str, Any]:
        """Stream provider deltas while retaining structured-output validation."""
        api_key = self.opencode_api_key()
        return await self._breaker.call(
            self._generate_stream_once, question, language, citations, on_token, api_key
        )

    async def _generate_stream_once(
        self,
        question: str,
        language: str,
        citations: list[Citation],
        on_token: Callable[[str], Awaitable[None]],
        api_key: str,
    ) -> dict[str, Any]:
        base_url = self.settings.opencode_go_base_url or self.settings.opencode_base_url
        body = self._body(question, language, citations)
        body["stream"] = True
        headers = {"Authorization": f"Bearer {api_key}"}
        content = ""
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(
                    timeout=self.settings.request_timeout_seconds
                ) as client, client.stream(
                    "POST",
                    f"{base_url.rstrip('/')}/chat/completions",
                    headers=headers,
                    json=body,
                ) as response:
                    if response.status_code in RETRYABLE_STATUS:
                        raise RetryableProviderError(
                            f"answer provider returned {response.status_code}"
                        )
                    if response.is_error:
                        self._raise_response_error(response.status_code)
                    emitted = 0
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if not data or data == "[DONE]":
                            continue
                        try:
                            event = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        choices = event.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta", {}).get("content") or ""
                        if isinstance(delta, list):
                            delta = "".join(part.get("text", "") for part in delta)
                        content += str(delta)
                        partial = self._partial_answer(content)
                        if partial is not None and len(partial) > emitted:
                            await on_token(partial[emitted:])
                            emitted = len(partial)
            except (httpx.TransportError, RetryableProviderError) as exc:
                if content or attempt == 2:
                    raise ProviderError("answer provider stream failed mid-response") from exc
                await asyncio.sleep(min(0.4 * (2**attempt), 4.0) + random.uniform(0, 0.25))
                continue
            break
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise ProviderError("answer provider returned invalid JSON") from exc

    @staticmethod
    def _partial_answer(content: str) -> str | None:
        marker = '"answer"'
        start = content.find(marker)
        if start < 0:
            return None
        start = content.find('"', content.find(":", start) + 1)
        if start < 0:
            return None
        raw = content[start + 1 :]
        escaped = False
        end = None
        for index, char in enumerate(raw):
            if char == '"' and not escaped:
                end = index
                break
            if char == "\\" and not escaped:
                escaped = True
            else:
                escaped = False
        if end is not None:
            raw = raw[:end]
        raw = raw.removesuffix("\\")
        try:
            return json.loads('"' + raw + '"')
        except json.JSONDecodeError:
            return None

    def opencode_api_key(self) -> str:
        key = self.settings.opencode_go_api_key or self.settings.opencode_api_key
        if not key:
            raise ProviderError(
                "OPENCODE_API_KEY is not configured. Set OPENCODE_API_KEY or "
                "OPENCODE_GO_API_KEY to generate grounded answers."
            )
        return key

    def _parse_response(self, response: httpx.Response) -> dict[str, Any]:
        if response.is_error:
            self._raise_response_error(response.status_code)
        payload = response.json()
        content = payload["choices"][0]["message"].get("content") or ""
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content)
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise ProviderError("answer provider returned invalid JSON") from exc

    @staticmethod
    def _raise_response_error(status_code: int) -> None:
        if status_code == 401:
            raise ProviderError(
                "OpenCode authentication failed (401). Check OPENCODE_API_KEY "
                "or OPENCODE_GO_API_KEY and the matching base URL, then restart the API."
            )
        raise ProviderError(f"answer provider returned {status_code}")


def decode_audio(value: str) -> bytes:
    if "," in value and value.startswith("data:"):
        value = value.split(",", 1)[1]
    return base64.b64decode(value, validate=True)
