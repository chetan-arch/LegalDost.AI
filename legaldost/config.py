"""Typed application settings loaded from environment variables (and an optional .env file)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"

    database_url: str = f"sqlite:///{(PROJECT_ROOT / 'data' / 'legaldost.db').as_posix()}"
    data_dir: Path = PROJECT_ROOT / "data"
    knowledge_dir: Path = PROJECT_ROOT / "knowledge"

    # Pseudonymisation of channel user ids (phone numbers). Must be a long random value in production.
    user_id_hash_secret: SecretStr = SecretStr("dev-only-change-me")

    # --- WhatsApp Cloud API -------------------------------------------------------------------
    whatsapp_enabled: bool = False
    whatsapp_verify_token: SecretStr | None = None
    whatsapp_app_secret: SecretStr | None = None
    whatsapp_access_token: SecretStr | None = None
    whatsapp_phone_number_id: str | None = None
    whatsapp_graph_api_version: str = "v23.0"
    whatsapp_graph_base_url: str = "https://graph.facebook.com"
    # Only honoured when environment == "development"; never enable in production.
    whatsapp_allow_unsigned_dev: bool = False

    # --- Admin --------------------------------------------------------------------------------
    admin_api_token: SecretStr | None = None

    # --- LLM ----------------------------------------------------------------------------------
    llm_provider: Literal["none", "anthropic", "ollama"] = "none"
    anthropic_api_key: SecretStr | None = None
    # Local, free models via Ollama (https://ollama.com). Nothing leaves this machine.
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:8b"
    ollama_num_ctx: int = 8192
    ollama_timeout_seconds: float = 180.0
    ollama_keep_alive: str = "30m"
    # Smaller models do better with fewer, shorter passages.
    ollama_max_passages: int = 4
    ollama_max_chars_per_passage: int = 1200
    llm_model_standard: str = "claude-opus-5-5"
    llm_effort_standard: Literal["low", "medium", "high", "xhigh", "max"] = "low"
    llm_model_deep: str = "claude-opus-5-5"
    llm_effort_deep: Literal["low", "medium", "high", "xhigh", "max"] = "high"
    llm_model_router: str = "claude-haiku-5-5"
    llm_refusal_fallback: bool = True
    llm_max_output_tokens: int = 4000
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 2
    llm_max_calls_per_question: int = 3
    llm_monthly_budget_usd: float = 25.0

    # --- Decision engine ----------------------------------------------------------------------
    decision_engine: Literal["rules", "jev", "llm"] = "rules"
    jev_api_key: SecretStr | None = None
    jev_base_url: str = "https://api.typesafe.ai"
    jev_model: str = "jev-latest"
    jev_timeout_seconds: float = 5.0
    jev_min_confidence: float = 0.6

    # --- Retrieval ----------------------------------------------------------------------------
    embedding_backend: Literal["hashing", "sentence-transformers"] = "hashing"
    embedding_model: str = "intfloat/multilingual-e5-small"
    embedding_dim: int = 256
    retrieval_max_passages: int = 6
    retrieval_candidate_pool: int = 40
    evidence_max_chars_per_passage: int = 1800
    # With a real semantic model, passages found by meaning alone (no keyword overlap) are kept
    # only above this cosine similarity.
    semantic_min_similarity: float = 0.86
    # Judgment passages found by meaning alone (no keyword match) must score at least this.
    judgment_semantic_min_similarity: float = 0.88

    # --- Ingestion ----------------------------------------------------------------------------
    ingest_max_file_mb: int = 25
    ingest_allowed_domains: list[str] = Field(
        default_factory=lambda: [
            "egazette.gov.in",
            "indiacode.nic.in",
            "www.indiacode.nic.in",
            "static.pib.gov.in",
            "morth.gov.in",
            "morth.nic.in",
            "main.sci.gov.in",
            "www.sci.gov.in",
            "api.sci.gov.in",
            "karnatakajudiciary.kar.nic.in",
            "transport.karnataka.gov.in",
            "dpal.kar.nic.in",
            "verdictum.in",
            "www.verdictum.in",
            "indian-supreme-court-judgments.s3.ap-south-1.amazonaws.com",
            "indian-high-court-judgments.s3.ap-south-1.amazonaws.com",
            "www.highcourtchd.gov.in",
            "aphc.gov.in",
            "cdn.ncw.gov.in",
            "sclsc.gov.in",
            "www.cra.tn.gov.in",
            "prsindia.org",
            "www.hptax.gov.in",
            "familycourts.mphc.gov.in",
            "www.labour.gov.in",
            "www.livelaw.in",
            "digiscr.sci.gov.in",
        ]
    )
    ingest_request_interval_seconds: float = 2.0
    keep_raw_source_files: bool = True

    # --- Languages ----------------------------------------------------------------------------
    # First entry is the default. Kannada ("kn") is implemented but switched off for now.
    supported_languages: list[str] = Field(default_factory=lambda: ["en"])

    # --- Privacy / abuse ----------------------------------------------------------------------
    conversation_retention_hours: int = 72
    gap_log_enabled: bool = True
    gap_log_retention_days: int = 30
    rate_limit_messages_per_hour: int = 30
    max_message_chars: int = 2000

    @field_validator(
        "whatsapp_verify_token",
        "whatsapp_app_secret",
        "whatsapp_access_token",
        "whatsapp_phone_number_id",
        "admin_api_token",
        "anthropic_api_key",
        "jev_api_key",
        mode="before",
    )
    @classmethod
    def _empty_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "sources"


@lru_cache
def get_settings() -> Settings:
    return Settings()
