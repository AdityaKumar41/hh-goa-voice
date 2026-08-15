from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    log_level: str = "INFO"
    elevenlabs_api_key: str | None = None
    elevenlabs_stt_url: str = "https://api.elevenlabs.io/v1/speech-to-text"
    elevenlabs_stt_model: str = "scribe_v2"
    opencode_api_key: str | None = None
    opencode_go_api_key: str | None = None
    opencode_base_url: str = "https://opencode.ai/zen/go/v1"
    opencode_go_base_url: str | None = None
    opencode_model: str = "deepseek-v4-flash"
    hf_token: str | None = None
    postgres_dsn: str = "postgresql://voice_rag:voice_rag@localhost:5432/voice_rag"
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "voice_rag_active"
    require_active_index: bool = False
    index_batch_size: int = 64
    embedding_model: str = "intfloat/multilingual-e5-small"
    index_version: str = "dev"
    prompt_version: str = "research-v1"
    trace_path: str = "data/traces.jsonl"
    max_audio_bytes: int = 12_000_000
    retrieval_top_k: int = 8
    min_retrieval_score: float = 0.20
    min_answer_overlap: float = 0.12
    max_context_chars: int = 12_000
    max_answer_chars: int = 900
    request_timeout_seconds: float = 20.0
    web_research_enabled: bool = False
    jina_reader_url: str = "https://r.jina.ai"
    firecrawl_api_key: str | None = None
    firecrawl_base_url: str = "https://api.firecrawl.dev/v2"
    web_timeout_seconds: float = 15.0
    max_web_chars: int = 20_000

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
