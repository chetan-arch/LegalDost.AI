"""Wiring of long-lived services. Tests construct ``Services`` directly with fakes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from sqlalchemy.orm import Session, sessionmaker

from legaldost.api.ratelimit import RateLimiter
from legaldost.config import Settings
from legaldost.db.models import Conversation
from legaldost.decision import build_decision_engine
from legaldost.decision.base import DecisionEngine
from legaldost.domain.registry import Registry, load_registry
from legaldost.llm import build_provider
from legaldost.llm.base import LLMProvider
from legaldost.pipeline.orchestrator import AnswerPipeline
from legaldost.retrieval.embeddings import Embedder, get_embedder


class TextSender(Protocol):
    def send_text(self, to_wa_id: str, body: str) -> str | None: ...


@dataclass
class Services:
    settings: Settings
    sessionmaker: sessionmaker[Session]
    registry: Registry
    embedder: Embedder
    provider: LLMProvider | None
    engine: DecisionEngine
    whatsapp: TextSender | None = None
    limiter: RateLimiter = field(default_factory=lambda: RateLimiter(30, 3600))

    def pipeline(self, session: Session, channel: str) -> AnswerPipeline:
        return AnswerPipeline(
            session, self.settings, self.registry, self.engine, self.embedder, self.provider, channel=channel
        )

    def conversation(self, session: Session, channel: str, key: str) -> Conversation:
        return self.pipeline(session, channel).store.get_or_create(channel, key)


def build_services(settings: Settings, factory: sessionmaker[Session]) -> Services:
    registry = load_registry()
    provider = build_provider(settings)
    engine = build_decision_engine(settings, registry, provider)
    whatsapp = None
    if settings.whatsapp_enabled and settings.whatsapp_access_token and settings.whatsapp_phone_number_id:
        from legaldost.channels.whatsapp import WhatsAppClient

        whatsapp = WhatsAppClient(
            settings.whatsapp_access_token.get_secret_value(),
            settings.whatsapp_phone_number_id,
            settings.whatsapp_graph_api_version,
            settings.whatsapp_graph_base_url,
        )
    return Services(
        settings=settings,
        sessionmaker=factory,
        registry=registry,
        embedder=get_embedder(),
        provider=provider,
        engine=engine,
        whatsapp=whatsapp,
        limiter=RateLimiter(settings.rate_limit_messages_per_hour, 3600),
    )
