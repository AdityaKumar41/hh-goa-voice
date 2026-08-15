"""Read-only research tools used behind the research harness seam."""

from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from .config import Settings


class ToolError(RuntimeError):
    pass


@dataclass(frozen=True)
class WebDocument:
    url: str
    title: str
    text: str
    provider: str


def validate_public_url(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ToolError("source_url must be a valid http or https URL")
    return value.strip()


class JinaReader:
    """Convert a public URL into readable text through Jina Reader."""

    def __init__(self, settings: Settings):
        self.settings = settings

    async def read(self, url: str) -> WebDocument:
        url = validate_public_url(url)
        endpoint = f"{self.settings.jina_reader_url.rstrip('/')}/{url}"
        async with httpx.AsyncClient(timeout=self.settings.web_timeout_seconds) as client:
            response = await client.get(endpoint, headers={"Accept": "text/plain"})
        if response.is_error:
            raise ToolError(f"Jina Reader returned {response.status_code}")
        text = response.text.strip()
        if not text:
            raise ToolError("Jina Reader returned no readable content")
        return WebDocument(url, urlparse(url).netloc, text[: self.settings.max_web_chars], "jina")


class FirecrawlReader:
    """Optional reader for JavaScript-heavy pages when a Firecrawl key exists."""

    def __init__(self, settings: Settings):
        self.settings = settings

    async def read(self, url: str) -> WebDocument:
        url = validate_public_url(url)
        if not self.settings.firecrawl_api_key:
            raise ToolError("FIRECRAWL_API_KEY is not configured")
        async with httpx.AsyncClient(timeout=self.settings.web_timeout_seconds) as client:
            response = await client.post(
                f"{self.settings.firecrawl_base_url.rstrip('/')}/scrape",
                headers={"Authorization": f"Bearer {self.settings.firecrawl_api_key}"},
                json={"url": url, "formats": ["markdown"], "onlyMainContent": True},
            )
        if response.is_error:
            raise ToolError(f"Firecrawl returned {response.status_code}")
        payload = response.json().get("data", response.json())
        text = payload.get("markdown") or payload.get("content") or ""
        if not text:
            raise ToolError("Firecrawl returned no readable content")
        return WebDocument(
            url,
            payload.get("title") or urlparse(url).netloc,
            text[: self.settings.max_web_chars],
            "firecrawl",
        )

    async def search(self, query: str, limit: int = 5) -> list[WebDocument]:
        if not self.settings.firecrawl_api_key:
            raise ToolError("FIRECRAWL_API_KEY is not configured")
        async with httpx.AsyncClient(timeout=self.settings.web_timeout_seconds) as client:
            response = await client.post(
                f"{self.settings.firecrawl_base_url.rstrip('/')}/search",
                headers={"Authorization": f"Bearer {self.settings.firecrawl_api_key}"},
                json={"query": query, "limit": limit},
            )
        if response.is_error:
            raise ToolError(f"Firecrawl search returned {response.status_code}")
        items = response.json().get("data", [])
        documents = []
        for item in items:
            url = item.get("url")
            text = item.get("markdown") or item.get("description") or item.get("content") or ""
            if url and text:
                documents.append(
                    WebDocument(
                        url,
                        item.get("title") or urlparse(url).netloc,
                        text[: self.settings.max_web_chars],
                        "firecrawl",
                    )
                )
        return documents


class ReadOnlyWebTool:
    """Select the configured web reader without exposing provider details to callers."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.jina = JinaReader(settings)
        self.firecrawl = FirecrawlReader(settings)

    async def read(self, url: str) -> WebDocument:
        if not self.settings.web_research_enabled:
            raise ToolError("web research is disabled")
        if self.settings.firecrawl_api_key:
            try:
                return await self.firecrawl.read(url)
            except ToolError:
                pass
        return await self.jina.read(url)

    async def search(self, query: str, limit: int = 5) -> list[WebDocument]:
        if not self.settings.web_research_enabled or not self.settings.firecrawl_api_key:
            return []
        return await self.firecrawl.search(query, limit)
