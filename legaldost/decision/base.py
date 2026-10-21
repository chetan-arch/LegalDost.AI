"""DecisionEngine interface.

A decision engine only *routes*: intent, domain, topic, complexity, and evidence priority. It
never establishes legal truth, never certifies an answer and never skips verification. Hard
constraints (safety triage, fact requirements, citation validation) stay in deterministic code.
"""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel

Intent = Literal["legal_question", "greeting", "out_of_scope"]


class RoutingDecision(BaseModel):
    intent: Intent
    domain: str | None = None
    topic: str | None = None
    complexity: Literal["simple", "complex"] = "simple"
    needs_deep_review: bool = False
    engine: str
    confidence: float | None = None
    latency_ms: int = 0
    fallback_used: bool = False
    error: str | None = None


class EvidenceCandidate(BaseModel):
    evidence_id: str
    title: str
    locator: str
    text: str


class DecisionEngine(Protocol):
    name: str

    def route(self, text: str, language: str, previous_topic: str | None = None) -> RoutingDecision: ...

    def prioritise_evidence(self, question: str, candidates: list[EvidenceCandidate]) -> list[str]:
        """Return evidence ids, most useful first. Must return only ids it was given."""
        ...
