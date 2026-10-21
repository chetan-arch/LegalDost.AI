"""Typed internal objects shared across the pipeline.

Citation objects shown to users are *never* produced by a model directly: they are built from
``EvidenceItem`` records that came out of the database (see ``pipeline/validator.py``).
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

Language = Literal["en", "kn"]


class AnswerMode(StrEnum):
    QUICK = "quick"
    EXPLAIN = "explain"
    EVIDENCE = "evidence"


class EvidenceStatus(StrEnum):
    SUFFICIENT = "sufficient"
    PARTIAL = "partially_supported"
    CONFLICTING = "conflicting"
    NONE = "no_reliable_evidence"
    HUMAN_REVIEW = "human_review_recommended"


# Lower rank = weaker. Used to make sure a model can lower but never raise the status.
STATUS_RANK: dict[EvidenceStatus, int] = {
    EvidenceStatus.NONE: 0,
    EvidenceStatus.HUMAN_REVIEW: 1,
    EvidenceStatus.CONFLICTING: 2,
    EvidenceStatus.PARTIAL: 3,
    EvidenceStatus.SUFFICIENT: 4,
}


class SourceCategory(StrEnum):
    PRIMARY_OFFICIAL = "primary_official"
    OFFICIAL_SECONDARY = "official_secondary"
    SECONDARY = "secondary"


class Escalation(StrEnum):
    NONE = "none"
    EMERGENCY = "emergency_services"
    ADVOCATE = "consult_advocate"
    LEGAL_AID = "legal_aid"
    SERIOUS_MATTER = "serious_matter_consult_advocate"


# --------------------------------------------------------------------------------------------
# Retrieval / evidence
# --------------------------------------------------------------------------------------------


class RetrievedPassage(BaseModel):
    passage_id: str
    source_id: str
    version_id: str
    score: float
    lexical_score: float
    vector_score: float
    matched_identifiers: list[str] = Field(default_factory=list)


class EvidenceItem(BaseModel):
    """One passage in the evidence packet, with the source metadata needed to cite it."""

    evidence_id: str  # "E1", "E2", ... stable within one packet
    passage_id: str
    source_id: str
    source_key: str
    title: str
    issuing_authority: str
    document_type: str
    source_category: SourceCategory
    jurisdiction: str
    court_level: str | None
    locator: str
    page_start: int | None
    page_end: int | None
    url: str
    text: str
    language: str
    publication_date: date | None
    commencement_date: date | None
    judgment_date: date | None
    legal_status: str
    verification_status: str
    host_note: str | None
    flags: list[str] = Field(default_factory=list)
    binding_note: str | None = None
    part_of: str | None = None  # statute chapter/part heading, e.g. "CHAPTER X — SPECIAL PROVISIONS ..."


class EvidencePacket(BaseModel):
    query: str
    jurisdiction: str | None
    items: list[EvidenceItem]

    def get(self, evidence_id: str) -> EvidenceItem | None:
        return next((i for i in self.items if i.evidence_id == evidence_id), None)


# --------------------------------------------------------------------------------------------
# Generation (model-facing) and validated answer (user-facing)
# --------------------------------------------------------------------------------------------

ClaimType = Literal["law_text", "interpretation", "application", "procedure"]


class DraftClaim(BaseModel):
    text: str = Field(description="One legal statement in plain language.")
    evidence_ids: list[str] = Field(description="Evidence ids (E1, E2...) that support this statement.")
    quote: str | None = Field(
        default=None, description="Short verbatim excerpt copied exactly from the first cited evidence item."
    )
    claim_type: ClaimType = "law_text"


class DraftAnswer(BaseModel):
    """What a generator returns. Nothing in here is trusted until validated."""

    summary: str
    legal_position: str
    claims: list[DraftClaim] = Field(default_factory=list)
    application_to_user_facts: str = ""
    important_exceptions: list[str] = Field(default_factory=list)
    missing_facts: list[str] = Field(default_factory=list)
    safe_next_steps: list[str] = Field(default_factory=list)
    proposed_status: EvidenceStatus = EvidenceStatus.PARTIAL
    conflict_note: str | None = None


class SourceCard(BaseModel):
    """A citation card rendered for the user. Built only from database records."""

    evidence_id: str
    passage_id: str
    source_key: str
    title: str
    reference: str
    source_category: SourceCategory
    document_type: str
    jurisdiction: str
    url: str
    excerpt: str
    publication_date: date | None
    commencement_date: date | None
    judgment_date: date | None
    legal_status: str
    verification_status: str
    host_note: str | None
    binding_note: str | None


class ValidatedClaim(BaseModel):
    text: str
    claim_type: ClaimType
    evidence_ids: list[str]
    quote: str | None
    support: Literal["quote_verified", "lexical", "weak"]


class ValidationReport(BaseModel):
    flags: list[str] = Field(default_factory=list)
    dropped_claims: int = 0
    kept_claims: int = 0
    unsupported_references: list[str] = Field(default_factory=list)
    blocked: bool = False
    summary_unsupported: bool = False
    removed_items: list[str] = Field(default_factory=list)
    application_unsupported: bool = False


class LegalAnswer(BaseModel):
    """The validated, structured answer. The formatter decides what to display."""

    kind: Literal["answer", "clarification", "abstain", "emergency", "declined", "info"] = "answer"
    language: Language = "en"
    summary: str
    legal_position: str = ""
    claims: list[ValidatedClaim] = Field(default_factory=list)
    supporting_sources: list[SourceCard] = Field(default_factory=list)
    application_to_user_facts: str = ""
    important_exceptions: list[str] = Field(default_factory=list)
    missing_facts: list[str] = Field(default_factory=list)
    safe_next_steps: list[str] = Field(default_factory=list)
    evidence_status: EvidenceStatus = EvidenceStatus.NONE
    status_reasons: list[str] = Field(default_factory=list)
    recommended_escalation: Escalation = Escalation.NONE
    assumptions: list[str] = Field(default_factory=list)
    generator: str = "none"
    validation: ValidationReport = Field(default_factory=ValidationReport)
    topic: str | None = None
    domain: str | None = None
