"""What the loaded corpus actually covers. Coverage is derived from data, never claimed in config."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from legaldost.db.models import DocumentVersion, LegalSource

EXCLUDED_STATUSES = ("superseded", "repealed", "withdrawn")


def corpus_domains(session: Session) -> set[str]:
    """Legal domains that have at least one available, current, successfully extracted source."""
    stmt = (
        select(LegalSource.legal_domains)
        .join(DocumentVersion, DocumentVersion.source_id == LegalSource.id)
        .where(DocumentVersion.is_current.is_(True))
        .where(DocumentVersion.extraction_status.in_(("succeeded", "partial")))
        .where(LegalSource.is_available.is_(True))
        .where(LegalSource.legal_status.not_in(EXCLUDED_STATUSES))
    )
    domains: set[str] = set()
    for (row,) in session.execute(stmt):
        domains.update(row or [])
    return domains
