from __future__ import annotations

from legaldost.config import Settings
from legaldost.llm.base import LLMProvider


def build_provider(settings: Settings) -> LLMProvider | None:
    """Return the configured provider, or None when no model is configured (extractive mode)."""
    if settings.llm_provider == "anthropic":
        # With no ANTHROPIC_API_KEY set, the SDK resolves other credential sources itself.
        from legaldost.llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider(settings)
    if settings.llm_provider == "ollama":
        from legaldost.llm.ollama_provider import OllamaProvider

        return OllamaProvider(settings)
    return None
