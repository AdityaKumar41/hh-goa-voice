import httpx
import pytest

from voice_rag.config import Settings
from voice_rag.tools import JinaReader, ReadOnlyWebTool, ToolError, validate_public_url


def test_validate_public_url_rejects_non_http_urls():
    with pytest.raises(ToolError):
        validate_public_url("file:///etc/passwd")


@pytest.mark.asyncio
async def test_jina_reader_returns_bounded_web_document(monkeypatch):
    async def request(self, url, **kwargs):
        assert url == "https://r.jina.ai/https://example.com/article"
        return httpx.Response(200, text="# Example\nReadable content")

    monkeypatch.setattr(httpx.AsyncClient, "get", request)
    document = await JinaReader(Settings(web_research_enabled=True)).read(
        "https://example.com/article"
    )
    assert document.provider == "jina"
    assert "Readable content" in document.text


@pytest.mark.asyncio
async def test_web_tool_is_disabled_by_default():
    with pytest.raises(ToolError, match="disabled"):
        await ReadOnlyWebTool(Settings()).read("https://example.com")
