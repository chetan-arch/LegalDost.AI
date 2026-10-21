"""Local LLM provider using Ollama's chat API with JSON-schema structured output.

Free and private: requests go to the Ollama server on this machine (``OLLAMA_BASE_URL``).
API reference: https://docs.ollama.com/api/chat (``format`` accepts a JSON schema; ``think: false``
turns off reasoning output on models that support it, such as Qwen3).
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx
from pydantic import ValidationError

from legaldost.config import Settings
from legaldost.llm.base import LLMBadOutput, LLMError, LLMResult, LLMUnavailable, T, Tier


class OllamaProvider:
    name = "ollama"

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None) -> None:
        self._settings = settings
        self._http = httpx.Client(
            base_url=settings.ollama_base_url, timeout=settings.ollama_timeout_seconds, transport=transport
        )

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
        s = self._settings
        body: dict[str, Any] = {
            "model": s.ollama_model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "format": schema.model_json_schema(),
            "stream": False,
            "think": False,
            "keep_alive": s.ollama_keep_alive,
            "options": {
                "temperature": 0,
                "num_ctx": s.ollama_num_ctx,
                "num_predict": max_tokens or s.llm_max_output_tokens,
            },
        }
        started = time.monotonic()
        try:
            resp = self._http.post("/api/chat", json=body)
        except httpx.TimeoutException as exc:
            raise LLMUnavailable("local model timed out") from exc
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"local model unreachable: {type(exc).__name__}") from exc
        if resp.status_code == 404:
            raise LLMError(f"model {s.ollama_model!r} is not installed (run: ollama pull {s.ollama_model})")
        if resp.status_code != 200:
            raise LLMUnavailable(f"local model error HTTP {resp.status_code}")
        data = resp.json()
        if data.get("done_reason") == "length":
            raise LLMBadOutput("output truncated (increase LLM_MAX_OUTPUT_TOKENS or OLLAMA_NUM_CTX)")
        content = (data.get("message") or {}).get("content") or ""
        try:
            parsed = schema.model_validate(json.loads(content))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise LLMBadOutput(
                f"local model returned invalid structured output: {type(exc).__name__}"
            ) from exc
        return LLMResult(
            output=parsed,
            model=str(data.get("model", s.ollama_model)),
            input_tokens=int(data.get("prompt_eval_count", 0)),
            output_tokens=int(data.get("eval_count", 0)),
            latency_ms=int((time.monotonic() - started) * 1000),
            cost_usd=0.0,
        )
