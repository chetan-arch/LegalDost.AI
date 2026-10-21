"""Anthropic Claude provider using the official SDK's structured-output ``parse`` helper.

Not exercised against the live API in this repository's tests (no key available); the unit tests
use a fake provider. Enable with ``LLM_PROVIDER=anthropic`` and ``ANTHROPIC_API_KEY``.
"""

from __future__ import annotations

import time
from typing import Any

import anthropic

from legaldost.config import Settings
from legaldost.llm.base import (
    LLMBadOutput,
    LLMError,
    LLMRefused,
    LLMResult,
    LLMUnavailable,
    T,
    Tier,
    estimate_cost,
)

# Server-side refusal fallback ("default" routing) is accepted on these models on the Claude API.
_FALLBACK_MODELS = {"claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-1", "claude-opus-5"}
_FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, settings: Settings) -> None:
        api_key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
        self._client = anthropic.Anthropic(
            api_key=api_key, timeout=settings.llm_timeout_seconds, max_retries=settings.llm_max_retries
        )
        self._settings = settings

    def _model_for(self, tier: Tier) -> tuple[str, str]:
        s = self._settings
        if tier == "router":
            return s.llm_model_router, "low"
        if tier == "deep":
            return s.llm_model_deep, s.llm_effort_deep
        return s.llm_model_standard, s.llm_effort_standard

    def structured(
        self,
        *,
        purpose: str,
        tier: Tier,
        system: str,
        user: str,
        schema: type[T],
        max_tokens: int | None = None,
    ) -> LLMResult[T]:
        model, effort = self._model_for(tier)
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens or self._settings.llm_max_output_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "output_config": {"effort": effort},
            "output_format": schema,
        }
        started = time.monotonic()
        response: Any
        try:
            if self._settings.llm_refusal_fallback and model in _FALLBACK_MODELS:
                response = self._client.beta.messages.parse(
                    **kwargs, betas=[_FALLBACK_BETA], fallbacks="default"
                )
            else:
                response = self._client.messages.parse(**kwargs)
        except anthropic.RateLimitError as exc:
            raise LLMUnavailable(f"rate limited: {exc.message}") from exc
        except anthropic.APITimeoutError as exc:
            raise LLMUnavailable("request timed out") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMUnavailable("connection error") from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500:
                raise LLMUnavailable(f"provider error {exc.status_code}") from exc
            raise LLMError(f"request rejected ({exc.status_code}): {exc.message}") from exc
        latency_ms = int((time.monotonic() - started) * 1000)
        if response.stop_reason == "refusal":
            raise LLMRefused("model declined the request")
        if response.stop_reason == "max_tokens":
            raise LLMBadOutput("output truncated at max_tokens")
        parsed = response.parsed_output
        if parsed is None:
            raise LLMBadOutput("no structured output returned")
        usage = response.usage
        return LLMResult(
            output=parsed,
            model=response.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            latency_ms=latency_ms,
            cost_usd=estimate_cost(model, usage.input_tokens, usage.output_tokens),
        )
