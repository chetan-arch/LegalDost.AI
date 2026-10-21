"""Deterministic keyword router: the default decision engine and the fallback for all others."""

from __future__ import annotations

import re
import time

from legaldost.decision.base import EvidenceCandidate, Intent, RoutingDecision
from legaldost.domain.registry import Registry

GREETING = re.compile(
    r"^\s*(hi|hello|hey|namaste|namaskara|good (morning|evening|afternoon)|ನಮಸ್ಕಾರ|ಹಾಯ್)\W*$", re.IGNORECASE
)
COMPLEX_HINTS = re.compile(
    r"\b(wrong (section|provision|rule)|cited the wrong|conflict|contradict|appeal|high court|supreme court|"
    r"court case|challenge|contest|which law applies|both)\b",
    re.IGNORECASE,
)


# Words that suggest a message is about law even when it matches no specific topic.
LEGAL_CUES = re.compile(
    r"\b(law|laws|legal|illegal|legally|rights?|court|case|judge|lawyer|advocate|police|notice|act|section|"
    r"rule|rules|article|complaint|sue|suing|penalty|fine|allowed|permitted|contract|agreement|liable|"
    r"compensation|petition|appeal|licen[cs]e|regulation|offen[cs]e|sanhita)\b|"
    r"ಕಾನೂನು|ಹಕ್ಕು|ನ್ಯಾಯಾಲಯ|ವಕೀಲ|ದೂರು|ನಿಯಮ",
    re.IGNORECASE,
)


def _score(text: str, phrases: list[str]) -> int:
    phrases = list(dict.fromkeys(phrases))  # duplicates must not inflate a topic's score
    lowered = text.lower()
    score = 0
    for phrase in phrases:
        p = phrase.lower()
        pattern = (r"(?<![a-z])" + re.escape(p) + r"(?![a-z])") if re.search(r"[a-z]", p) else re.escape(p)
        if re.search(pattern, lowered):
            score += 2 if " " in p else 1
    return score


class RulesDecisionEngine:
    name = "rules"

    def __init__(self, registry: Registry) -> None:
        self.registry = registry

    def topic_scores(self, text: str) -> dict[str, int]:
        scores = {}
        for key, topic in self.registry.topics.items():
            phrases = [p for plist in topic.keywords.values() for p in plist]
            s = _score(text, phrases)
            if s:
                scores[key] = s
        return scores

    def route(self, text: str, language: str, previous_topic: str | None = None) -> RoutingDecision:
        started = time.monotonic()
        if GREETING.match(text):
            return RoutingDecision(intent="greeting", engine=self.name, latency_ms=0)
        scores = self.topic_scores(text)
        topic = None
        if scores:
            # Within a domain, prefer a specific topic over that domain's ".general" topic, but
            # carry the domain's total evidence so a generic-but-strong match is not outvoted.
            best: dict[str, tuple[int, str]] = {}
            for key, score in scores.items():
                domain_key = self.registry.topics[key].domain
                total = sum(v for k, v in scores.items() if self.registry.topics[k].domain == domain_key)
                current = best.get(domain_key)
                is_specific = not key.endswith(".general")
                if current is None or (is_specific, score) > (
                    not current[1].endswith(".general"),
                    scores[current[1]],
                ):
                    best[domain_key] = (total, key)
            topic = max(best.values(), key=lambda v: (v[0], v[1]))[1]
        domain = self.registry.topics[topic].domain if topic else None
        domains_hit = {self.registry.topics[k].domain for k in scores}
        complex_ = len(domains_hit) > 1 or len(text) > 600 or bool(COMPLEX_HINTS.search(text))
        intent: Intent = "legal_question" if topic or previous_topic else "out_of_scope"
        if not topic and LEGAL_CUES.search(text):
            intent = "legal_question"  # legal, but no specific topic: the catch-all searches everything
        return RoutingDecision(
            intent=intent,
            domain=domain,
            topic=topic,
            complexity="complex" if complex_ else "simple",
            needs_deep_review=complex_,
            engine=self.name,
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    def prioritise_evidence(self, question: str, candidates: list[EvidenceCandidate]) -> list[str]:
        return [c.evidence_id for c in candidates]  # keep retrieval order
