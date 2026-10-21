"""Optional Jev (TypeSafe) adapter.

Implements the HTTP API as documented at https://docs.typesafe.ai/api.md (checked 2026-10-17):

    POST {JEV_BASE_URL}/v1/systemone
    Authorization: Bearer <JEV_API_KEY>
    {"state": ..., "model": "jev-latest", "questions": {id: {"type": "choice"|"noul"|"score", ...}}}
    -> {"model": "...", "answers": {id: {...}}, "usage": {"input_tokens": n, "output_tokens": n}}

Note: the docs' Choice page example uses ``selectedModels`` while the API reference uses
``model``; this adapter follows the API reference. Not tested against the live service (no key).

Every failure, low-confidence answer or out-of-registry value falls back to the rules engine.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from legaldost.decision.base import EvidenceCandidate, RoutingDecision
from legaldost.decision.rules import RulesDecisionEngine
from legaldost.domain.registry import Registry


class JevError(Exception):
    pass


class JevClient:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float,
        transport: httpx.BaseTransport | None = None,
        max_retries: int = 2,
    ) -> None:
        self._http = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            transport=transport,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )
        self.model = model
        self.max_retries = max_retries
        self.last_usage: dict[str, int] = {}

    def evaluate(self, state: Any, questions: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        body = {"state": state, "model": self.model, "questions": questions}
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._http.post("/v1/systemone", json=body)
            except httpx.HTTPError as exc:
                if attempt == self.max_retries:
                    raise JevError(f"transport error: {type(exc).__name__}") from exc
                time.sleep(0.2 * 2**attempt)
                continue
            if resp.status_code in (429, 529) and attempt < self.max_retries:
                time.sleep(0.2 * 2**attempt)
                continue
            if resp.status_code != 200:
                raise JevError(f"HTTP {resp.status_code}")
            data = resp.json()
            answers = data.get("answers")
            if not isinstance(answers, dict):
                raise JevError("response missing answers")
            self.last_usage = data.get("usage") or {}
            return answers
        raise JevError("retries exhausted")


class JevDecisionEngine:
    name = "jev"

    def __init__(self, registry: Registry, client: JevClient, min_confidence: float = 0.6) -> None:
        self.registry = registry
        self.client = client
        self.min_confidence = min_confidence
        self.fallback = RulesDecisionEngine(registry)

    def _questions(self) -> dict[str, dict[str, Any]]:
        topics: dict[str, Any] = {k: t.label.en for k, t in self.registry.topics.items()}
        topics["none"] = "Not about any of these legal topics"
        return {
            "intent": {
                "type": "choice",
                "instructions": "What is the user doing in this message?",
                "criteria": {
                    "legal_question": "Asking about a legal situation, rights, a fine, a notice or a law",
                    "greeting": "Only greeting or small talk",
                    "out_of_scope": "Something unrelated to law",
                },
            },
            "topic": {
                "type": "choice",
                "instructions": "Which legal topic does the user's message mainly concern?",
                "criteria": topics,
            },
            "complex": {
                "type": "noul",
                "instructions": "Does the message involve more than one legal issue, a dispute about which law or "
                "provision applies, a court case, or a serious consequence?",
            },
        }

    def route(self, text: str, language: str, previous_topic: str | None = None) -> RoutingDecision:
        started = time.monotonic()
        rules = self.fallback.route(text, language, previous_topic)
        try:
            answers = self.client.evaluate(
                {"message": text, "language": language, "previous_topic": previous_topic}, self._questions()
            )
        except JevError as exc:
            return rules.model_copy(update={"fallback_used": True, "error": str(exc), "engine": "jev->rules"})
        latency = int((time.monotonic() - started) * 1000)
        intent_a, topic_a, complex_a = (
            answers.get("intent", {}),
            answers.get("topic", {}),
            answers.get("complex", {}),
        )
        intent = intent_a.get("choice")
        topic = topic_a.get("choice")
        confidence = topic_a.get("confidence")
        fallback = False
        if intent not in ("legal_question", "greeting", "out_of_scope") or (
            (intent_a.get("confidence") or 0) < self.min_confidence
        ):
            intent, fallback = rules.intent, True
        if topic == "none":
            topic = None
        if topic is not None and (
            topic not in self.registry.topics or (confidence or 0) < self.min_confidence
        ):
            topic, fallback = rules.topic, True
        noul = complex_a.get("noul")
        is_complex = bool(noul >= 0.5) if isinstance(noul, int | float) else rules.complexity == "complex"
        return RoutingDecision(
            intent=intent,
            topic=topic,
            domain=self.registry.topics[topic].domain if topic else None,
            complexity="complex" if is_complex else "simple",
            needs_deep_review=is_complex,
            engine="jev",
            confidence=confidence,
            latency_ms=latency,
            fallback_used=fallback,
        )

    def prioritise_evidence(self, question: str, candidates: list[EvidenceCandidate]) -> list[str]:
        if not candidates:
            return []
        questions = {
            c.evidence_id: {
                "type": "score",
                "instructions": f"How directly does passage {c.evidence_id} in the state address the user's question?",
                "criteria": [
                    "Unrelated",
                    "Mentions the topic",
                    "Relevant background",
                    "Directly addresses it",
                ],
            }
            for c in candidates
        }
        state = {"user_question": question, "passages": {c.evidence_id: c.text[:1500] for c in candidates}}
        try:
            answers = self.client.evaluate(state, questions)
        except JevError:
            return self.fallback.prioritise_evidence(question, candidates)
        given = [c.evidence_id for c in candidates]

        def score(eid: str) -> float:
            value = answers.get(eid, {}).get("score")
            return float(value) if isinstance(value, int | float) else -1.0

        return sorted(given, key=lambda eid: (-score(eid), given.index(eid)))
