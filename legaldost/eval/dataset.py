"""Evaluation dataset schema.

Designed so Indian advocates can review and annotate each case (``review`` block) without
touching code. Expectations are about *behaviour and evidence*, never hard-coded legal
conclusions: acceptable conclusions are recorded by reviewers in ``review.acceptable_conclusions``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

Outcome = Literal[
    "answer",
    "clarification",
    "abstain",
    "unsupported_domain",
    "emergency",
    "declined",
    "unknown_topic",
    "help",
    "mode_explain",
    "mode_evidence",
    "deleted",
    "reset",
    "language_unsupported",
]


class TurnExpectation(BaseModel):
    outcome: list[Outcome] = Field(default_factory=list, description="any of these outcomes is acceptable")
    asks_for: list[str] = Field(default_factory=list, description="facts the clarification must ask for")
    allowed_status: list[str] = Field(default_factory=list)
    expected_sources: list[str] = Field(default_factory=list, description="source_keys that should be cited")
    forbidden_sources: list[str] = Field(default_factory=list)
    min_citations: int = 0
    must_contain: list[str] = Field(
        default_factory=list, description="case-insensitive substrings of the reply"
    )
    must_not_contain: list[str] = Field(default_factory=list)
    binding_note_required: bool = False


class Turn(BaseModel):
    user: str
    expect: TurnExpectation = Field(default_factory=TurnExpectation)


class Review(BaseModel):
    status: Literal["unreviewed", "in_review", "approved", "needs_changes"] = "unreviewed"
    reviewer: str | None = None
    reviewed_on: str | None = None
    expected_evidence: list[str] = Field(
        default_factory=list, description="source_key#locator the advocate expects"
    )
    acceptable_conclusions: list[str] = Field(default_factory=list)
    unacceptable_conclusions: list[str] = Field(default_factory=list)
    notes: str = ""


class EvalCase(BaseModel):
    id: str
    category: Literal[
        "statutory",
        "multi_source",
        "ambiguous",
        "missing_facts",
        "outdated_reference",
        "conflicting",
        "incorrect_assumption",
        "unsupported_conclusion",
        "prompt_injection",
        "unanswerable",
        "unsupported_domain",
        "safety",
        "language",
        "mode",
    ]
    language: Literal["en", "kn"] = "en"
    jurisdiction: str | None = None
    description: str = ""
    turns: list[Turn]
    review: Review = Field(default_factory=Review)


class EvalDataset(BaseModel):
    name: str
    corpus_note: str = ""
    cases: list[EvalCase]


def load_dataset(path: Path) -> EvalDataset:
    with path.open(encoding="utf-8") as fh:
        return EvalDataset.model_validate(yaml.safe_load(fh))
