"""Benchmark decision engines (rules / jev / llm) on a labelled routing set.

Reports topic & intent accuracy, latency (p50/p95, measured here, not vendor-reported),
fallback/error counts and token usage when the engine reports it. Engines without credentials are
skipped with a clear message rather than simulated.
"""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from legaldost.config import get_settings
from legaldost.decision.base import DecisionEngine
from legaldost.decision.rules import RulesDecisionEngine
from legaldost.domain.registry import Registry, load_registry


class RoutingCase(BaseModel):
    id: str
    message: str
    language: str = "en"
    intent: str
    topic: str | None


def load_routing(path: Path) -> list[RoutingCase]:
    with path.open(encoding="utf-8") as fh:
        return [RoutingCase.model_validate(c) for c in yaml.safe_load(fh)["cases"]]


def _engine(name: str, registry: Registry) -> tuple[DecisionEngine | None, str | None]:
    settings = get_settings()
    if name == "rules":
        return RulesDecisionEngine(registry), None
    if name == "jev":
        if not settings.jev_api_key:
            return None, "JEV_API_KEY not set; Jev benchmark skipped (no simulated results)"
        from legaldost.decision.jev import JevClient, JevDecisionEngine

        client = JevClient(
            settings.jev_api_key.get_secret_value(),
            settings.jev_base_url,
            settings.jev_model,
            settings.jev_timeout_seconds,
        )
        return JevDecisionEngine(registry, client, settings.jev_min_confidence), None
    if name == "llm":
        from legaldost.llm import build_provider

        provider = build_provider(settings)
        if provider is None:
            return None, "LLM_PROVIDER=none; LLM router benchmark skipped"
        from legaldost.decision.llm_router import LLMDecisionEngine

        return LLMDecisionEngine(registry, provider), None
    return None, f"unknown engine {name}"


def benchmark(engine: DecisionEngine, cases: list[RoutingCase]) -> dict[str, Any]:
    latencies, topic_ok, intent_ok, fallbacks, errors, misses = [], 0, 0, 0, 0, []
    tokens_in = tokens_out = 0
    for case in cases:
        started = time.perf_counter()
        decision = engine.route(case.message, case.language)
        latencies.append((time.perf_counter() - started) * 1000)
        topic_ok += decision.topic == case.topic
        intent_ok += decision.intent == case.intent
        fallbacks += decision.fallback_used
        errors += decision.error is not None
        if decision.topic != case.topic:
            misses.append({"id": case.id, "expected": case.topic, "got": decision.topic})
        usage = getattr(getattr(engine, "client", None), "last_usage", None) or {}
        tokens_in += int(usage.get("input_tokens", 0))
        tokens_out += int(usage.get("output_tokens", 0))
    n = len(cases)
    q = statistics.quantiles(latencies, n=20) if n >= 2 else latencies * 19
    return {
        "engine": engine.name,
        "cases": n,
        "topic_accuracy": round(topic_ok / n, 3),
        "intent_accuracy": round(intent_ok / n, 3),
        "latency_ms_p50": round(statistics.median(latencies), 2),
        "latency_ms_p95": round(q[18], 2),
        "fallbacks": fallbacks,
        "errors": errors,
        "input_tokens": tokens_in,
        "output_tokens": tokens_out,
        "misses": misses,
    }


def run_routing_benchmark(dataset: Path, engines: list[str], out: Path | None = None) -> int:
    registry = load_registry()
    cases = load_routing(dataset)
    report: dict[str, Any] = {"dataset": str(dataset.name), "results": [], "skipped": []}
    for name in engines:
        engine, reason = _engine(name.strip(), registry)
        if engine is None:
            report["skipped"].append({"engine": name, "reason": reason})
            continue
        report["results"].append(benchmark(engine, cases))
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if out:
        out.write_text(text, encoding="utf-8")
    print(text)
    return 0
