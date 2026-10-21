"""Deterministic evidence-status and escalation rules.

The generator's proposed status is an upper bound it may *lower*; it can never raise the status
above the cap computed here from the validated evidence and the established facts.
"""

from __future__ import annotations

from legaldost.domain.schemas import (
    STATUS_RANK,
    DraftAnswer,
    Escalation,
    EvidenceStatus,
    SourceCard,
    SourceCategory,
    ValidatedClaim,
    ValidationReport,
)
from legaldost.safety import TriageCategory, TriageResult
from legaldost.strings import STRINGS, t


def _min(a: EvidenceStatus, b: EvidenceStatus) -> EvidenceStatus:
    return a if STATUS_RANK[a] <= STATUS_RANK[b] else b


def fact_label(name: str, language: str) -> str:
    return t(f"fact_{name}", language) if f"fact_{name}" in STRINGS else name


def determine_status(
    draft: DraftAnswer,
    claims: list[ValidatedClaim],
    cards: list[SourceCard],
    report: ValidationReport,
    missing_required: list[str],
    generator: str,
    triage: TriageResult,
    user_jurisdiction: str | None,
    language: str = "en",
    high_risk: bool = False,
) -> tuple[EvidenceStatus, list[str], Escalation]:
    reasons: list[str] = []
    escalation = Escalation.NONE

    def r(key: str, **kw: object) -> None:
        reasons.append(t(key, language, **kw))

    if not claims or not cards:
        r("r_no_claims")
        return EvidenceStatus.NONE, reasons, escalation

    cap = EvidenceStatus.SUFFICIENT
    if missing_required:
        cap = _min(cap, EvidenceStatus.PARTIAL)
        r("r_missing_facts", facts=", ".join(fact_label(f, language) for f in missing_required))
    primary = [c for c in cards if c.source_category == SourceCategory.PRIMARY_OFFICIAL]
    if not primary:
        cap = _min(cap, EvidenceStatus.PARTIAL)
        r("r_no_primary")
    if primary and all(c.legal_status == "unknown" for c in primary):
        cap = _min(cap, EvidenceStatus.PARTIAL)
        r("r_status_unknown")
    if not any(c.verification_status == "reviewer_verified" for c in cards):
        cap = _min(cap, EvidenceStatus.PARTIAL)
        r("r_unreviewed")
    if all(c.binding_note for c in cards):
        cap = _min(cap, EvidenceStatus.PARTIAL)
        r("r_not_binding")
    if generator == "extractive":
        cap = _min(cap, EvidenceStatus.PARTIAL)
        r("r_extractive")
    if report.dropped_claims:
        r("r_dropped", n=report.dropped_claims)
    if report.blocked:
        cap = _min(cap, EvidenceStatus.PARTIAL)
        r("r_blocked")

    status = _min(draft.proposed_status, cap)
    if draft.proposed_status == EvidenceStatus.CONFLICTING:
        if len({c.source_key for c in cards}) >= 2:
            status = EvidenceStatus.CONFLICTING
            reasons.append(draft.conflict_note or t("r_conflict", language))
            escalation = Escalation.ADVOCATE
        else:
            status = _min(status, EvidenceStatus.PARTIAL)

    if triage.category == TriageCategory.LIBERTY:
        status = EvidenceStatus.HUMAN_REVIEW
        escalation = Escalation.LEGAL_AID
        r("r_liberty")
    elif triage.category == TriageCategory.DEADLINE:
        status = _min(status, EvidenceStatus.HUMAN_REVIEW)
        escalation = Escalation.ADVOCATE
        r("r_deadline")
    if high_risk and escalation == Escalation.NONE:
        escalation = Escalation.SERIOUS_MATTER
        r("r_high_risk")
    if not user_jurisdiction:
        r("r_no_jurisdiction")
    return status, reasons, escalation
