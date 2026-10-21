from __future__ import annotations

from legaldost.config import Settings
from legaldost.decision.base import DecisionEngine
from legaldost.decision.rules import RulesDecisionEngine
from legaldost.domain.registry import Registry
from legaldost.llm.base import LLMProvider


def build_decision_engine(
    settings: Settings, registry: Registry, provider: LLMProvider | None
) -> DecisionEngine:
    if settings.decision_engine == "jev":
        if not settings.jev_api_key:
            raise RuntimeError("DECISION_ENGINE=jev requires JEV_API_KEY")
        from legaldost.decision.jev import JevClient, JevDecisionEngine

        client = JevClient(
            settings.jev_api_key.get_secret_value(),
            settings.jev_base_url,
            settings.jev_model,
            settings.jev_timeout_seconds,
        )
        return JevDecisionEngine(registry, client, settings.jev_min_confidence)
    if settings.decision_engine == "llm":
        if provider is None:
            raise RuntimeError("DECISION_ENGINE=llm requires an LLM provider")
        from legaldost.decision.llm_router import LLMDecisionEngine

        return LLMDecisionEngine(registry, provider)
    return RulesDecisionEngine(registry)
