from fastapi.testclient import TestClient

from voice_rag import app
from voice_rag.app import app as fastapi_app
from voice_rag.providers import ProviderError
from voice_rag.retrieval import InMemoryRetriever, SearchDocument


def test_provider_failures_are_reported_as_bad_gateway(monkeypatch):
    async def fail(*_args, **_kwargs):
        raise ProviderError("OpenCode authentication failed (401). Check OPENCODE_API_KEY")

    monkeypatch.setattr(app.pipeline.generator, "generate", fail)
    monkeypatch.setattr(
        app.pipeline, "retriever", InMemoryRetriever([SearchDocument("p1", "Goa is in India", "en", 0.9)])
    )

    response = TestClient(fastapi_app).post(
        "/api/query",
        json={"text": "Where is Goa?"},
    )

    assert response.status_code == 502
    assert "OPENCODE_API_KEY" in response.json()["detail"]


def test_health_reports_demo_index_without_active_qdrant(monkeypatch):
    monkeypatch.setattr(app.pipeline, "retriever", InMemoryRetriever([]))
    monkeypatch.setattr(app.settings, "app_env", "development")
    monkeypatch.setattr(app.settings, "require_active_index", False)

    response = TestClient(fastapi_app).get("/api/health")

    assert response.json()["dependencies"]["qdrant"] == "demo"
    assert response.json()["status"] == "ok"


def test_production_refuses_to_serve_without_active_index(monkeypatch):
    monkeypatch.setattr(app.pipeline, "retriever", InMemoryRetriever([]))
    monkeypatch.setattr(app.settings, "app_env", "production")
    monkeypatch.setattr(app.settings, "require_active_index", True)

    response = TestClient(fastapi_app).post("/api/query", json={"text": "Where is Goa?"})

    assert response.status_code == 503
    assert "index is active" in response.json()["detail"]
