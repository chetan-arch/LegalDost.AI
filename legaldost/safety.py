"""Deterministic safety triage, run before any retrieval or model call.

These are hard constraints and are intentionally not delegated to a model or to Jev.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum


class TriageCategory(StrEnum):
    NONE = "none"
    EMERGENCY = "emergency"
    PROHIBITED = "prohibited"
    LIBERTY = "liberty"
    DEADLINE = "deadline"


_EMERGENCY = [
    r"\b(being|getting) (beaten|attacked|assaulted|hit)\b",
    r"\bbeating me\b",
    r"\battacking me\b",
    r"\bthreaten(ing|ed)? to (kill|hurt|beat)\b",
    r"\bkidnap",
    r"\b(kill|hurt|harm) myself\b",
    r"\bsuicid",
    r"\bbleeding\b",
    r"\b(seriously|badly) (injured|hurt)\b",
    r"\bunconscious\b",
    r"\bsomeone is following me\b",
    r"\bin danger\b",
    r"\bsexual(ly)? (assault|harass)",
    "ಹೊಡೆಯುತ್ತಿದ್ದಾರೆ",
    "ಅಪಾಯದಲ್ಲಿ",
    "ಆತ್ಮಹತ್ಯೆ",
]
_PROHIBITED = [
    r"\bbribe",
    r"\bpay (off|them off)\b",
    r"\bhow much (should|do) i (pay|give) (the )?(police|officer|cop)",
    r"\b(escape|run away|flee) from (the )?police\b",
    r"\bavoid (getting )?caught\b",
    r"\bhide from (the )?police\b",
    r"\bfake (licen[cs]e|document|rc|insurance|puc|number plate)",
    r"\bforge(d|ry)?\b",
    r"\b(destroy|delete|hide) (the )?evidence\b",
    r"\b(hit|fight|push) the (officer|police|cop)\b",
    r"\bnot (stop|pull over) for (the )?police\b",
    r"\bcover (the )?number plate\b",
    "ಲಂಚ",
]
_LIBERTY = [
    r"\barrest(ed|ing)?\b",
    r"\bdetain(ed)?\b",
    r"\b(police|judicial) custody\b",
    r"\bbail\b",
    r"\bfir (against|on) me\b",
    r"\bjail\b",
    r"\block(ed)? up\b",
    r"\bcriminal case\b",
    "ಬಂಧನ",
    "ಬಂಧಿಸಿ",
    "ಜಾಮೀನು",
]
_DEADLINE = [
    r"\bdeadline\b",
    r"\blast date\b",
    r"\bcourt (date|hearing)\b",
    r"\bsummons\b",
    r"\bhearing (is )?(tomorrow|today|next week)\b",
    r"\bwithin \d+ days\b",
]


def _compile(patterns: list[str]) -> list[re.Pattern[str]]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


_RULES: list[tuple[TriageCategory, list[re.Pattern[str]]]] = [
    (TriageCategory.EMERGENCY, _compile(_EMERGENCY)),
    (TriageCategory.PROHIBITED, _compile(_PROHIBITED)),
    (TriageCategory.LIBERTY, _compile(_LIBERTY)),
    (TriageCategory.DEADLINE, _compile(_DEADLINE)),
]


@dataclass
class TriageResult:
    category: TriageCategory = TriageCategory.NONE
    signals: list[str] = field(default_factory=list)

    @property
    def needs_escalation(self) -> bool:
        return self.category in (TriageCategory.LIBERTY, TriageCategory.DEADLINE)


def triage(text: str) -> TriageResult:
    """Return the highest-priority category whose patterns match (emergency first)."""
    for category, patterns in _RULES:
        hits = [p.pattern for p in patterns if p.search(text)]
        if hits:
            return TriageResult(category=category, signals=hits)
    return TriageResult()


# Instruction-like text inside legal documents (possible prompt injection). Used at ingestion
# time to flag passages; flagged passages are never sent to a model.
_INJECTION = _compile(
    [
        r"\bignore (all |any )?(previous|prior|above) (instructions|prompts)\b",
        r"\b(you are|act as) (now )?(an? )?(ai|assistant|chatbot|language model)\b",
        r"\bsystem prompt\b",
        r"\bdisregard (the|all) (rules|instructions)\b",
        r"\b(respond|answer|reply) (only )?with\b.*\b(json|yes|no)\b",
        r"\bdo not (cite|mention) (any )?sources\b",
    ]
)


def looks_like_injection(text: str) -> bool:
    return any(p.search(text) for p in _INJECTION)
