import httpx
import pytest

from voice_rag.config import Settings
from voice_rag.providers import (
    AnswerGenerator,
    CircuitBreaker,
    ProviderError,
    SpeechToText,
    retry_async,
)


@pytest.mark.asyncio
async def test_stt_sends_production_scribe_model(monkeypatch):
    seen = {}

    async def request(self, url, **kwargs):
        seen.update(kwargs["data"])
        return httpx.Response(200, json={"text": "hello"})

    monkeypatch.setattr(httpx.AsyncClient, "post", request)
    result = await SpeechToText(Settings(elevenlabs_api_key="test")).transcribe(b"audio")
    assert result == "hello"
    assert seen["model_id"] == "scribe_v2"


@pytest.mark.asyncio
async def test_opencode_go_credentials_use_go_endpoint(monkeypatch):
    seen = {}

    async def request(self, url, **kwargs):
        seen["url"] = url
        seen["authorization"] = kwargs["headers"]["Authorization"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"answer":"Goa","confidence":0.9,"grounded":true,"refused":false,"citation_ids":["p1"]}'
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", request)
    settings = Settings(
        opencode_go_api_key="go-test",
        opencode_go_base_url="https://opencode.ai/zen/go/v1",
    )
    await AnswerGenerator(settings).generate(
        "Where is Goa?",
        "en",
        [type("Citation", (), {"passage_id": "p1", "text": "Goa is in India."})()],
    )

    assert seen == {
        "url": "https://opencode.ai/zen/go/v1/chat/completions",
        "authorization": "Bearer go-test",
    }


@pytest.mark.asyncio
async def test_generator_retries_transient_status_then_succeeds(monkeypatch):
    calls = {"count": 0}

    async def request(self, url, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(503, json={})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"answer":"Goa","confidence":0.9,"grounded":true,"refused":false,"citation_ids":["p1"]}'
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", request)
    result = await AnswerGenerator(Settings(opencode_api_key="k")).generate(
        "Where is Goa?",
        "en",
        [type("Citation", (), {"passage_id": "p1", "text": "Goa is in India."})()],
    )
    assert calls["count"] == 2
    assert result["answer"] == "Goa"


@pytest.mark.asyncio
async def test_generate_stream_skips_reasoning_only_deltas(monkeypatch):
    lines = [
        'data: {"choices":[{"delta":{"content":null,"reasoning_content":"thinking"}}]}',
        'data: {"choices":[{"delta":{"content":"{\\"answer\\":\\"Goa\\""}}]}',
        'data: {"choices":[{"delta":{"content":"}"}}]}',
        "data: [DONE]",
    ]
    stream = _FakeAsyncStream(lines)

    monkeypatch.setattr(
        httpx.AsyncClient,
        "stream",
        lambda self, method, url, **kwargs: stream,
    )
    tokens: list[str] = []

    async def on_token(token: str) -> None:
        tokens.append(token)

    result = await AnswerGenerator(Settings(opencode_api_key="k")).generate_stream(
        "Where is Goa?",
        "en",
        [type("Citation", (), {"passage_id": "p1", "text": "Goa is in India."})()],
        on_token,
    )
    assert result["answer"] == "Goa"
    assert "".join(tokens) == "Goa"


@pytest.mark.asyncio
async def test_retry_async_gives_up_after_exhaustion(monkeypatch):
    from voice_rag.providers import RetryableProviderError

    calls = {"count": 0}

    async def always_fail():
        calls["count"] += 1
        raise RetryableProviderError("boom")

    with pytest.raises(ProviderError):
        await retry_async(always_fail, attempts=3, base_delay=0.01)
    assert calls["count"] == 3


class _FakeAsyncStream:
    status_code = 200
    is_error = False

    def __init__(self, lines):
        self._lines = iter(lines)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def aiter_lines(self):
        for line in self._lines:
            yield line


@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_threshold():
    breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=60)

    async def fail():
        raise RuntimeError("downstream failed")

    with pytest.raises(RuntimeError):
        await breaker.call(fail)
    with pytest.raises(RuntimeError):
        await breaker.call(fail)

    assert breaker.open is True
    with pytest.raises(ProviderError, match="circuit breaker is open"):
        await breaker.call(fail)
