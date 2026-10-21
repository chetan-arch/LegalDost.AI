"""Controlled ingestion: register sources, add versions, extract, index, reprocess, change status.

Nothing is ever hard-deleted: superseded or unavailable sources keep their versions and
passages for provenance, they are just excluded from retrieval.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from legaldost.config import Settings
from legaldost.db.models import DocumentVersion, IngestionEvent, LegalSource, Passage, utcnow
from legaldost.ingestion.extract import ExtractionError, extract, sniff_mime
from legaldost.ingestion.segment import segment
from legaldost.retrieval.embeddings import Embedder
from legaldost.safety import looks_like_injection
from legaldost.textutil import sha256_text

log = logging.getLogger(__name__)

DocumentType = Literal[
    "statute", "rules", "notification", "judgment", "official_summary", "secondary_commentary"
]
SourceCategoryT = Literal["primary_official", "official_secondary", "secondary"]
LegalStatus = Literal[
    "unknown", "in_force", "amended", "partially_in_force", "superseded", "repealed", "withdrawn"
]
VerificationStatus = Literal["unverified", "fetched_unreviewed", "reviewer_verified"]


class SourceSpec(BaseModel):
    """Metadata for registering a source. Unknown values must stay None/'unknown'."""

    source_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,119}$")
    title: str
    issuing_authority: str
    document_type: DocumentType
    source_category: SourceCategoryT
    jurisdiction: str = Field(pattern=r"^IN(-[A-Z]{2})?$")
    court_level: str | None = None
    legal_domains: list[str] = Field(default_factory=list)
    identifiers: dict[str, Any] = Field(default_factory=dict)
    source_url: HttpUrl
    host_note: str | None = None
    languages: list[str] = Field(default_factory=lambda: ["en"])
    publication_date: date | None = None
    commencement_date: date | None = None
    judgment_date: date | None = None
    legal_status: LegalStatus = "unknown"
    status_note: str | None = None
    licensing_note: str | None = None

    @field_validator("source_url")
    @classmethod
    def _https(cls, v: HttpUrl) -> HttpUrl:
        if v.scheme != "https":
            raise ValueError("source_url must be https")
        return v


class IngestOutcome(BaseModel):
    source_key: str
    version_id: str | None
    status: Literal["created", "duplicate", "failed"]
    passages: int = 0
    message: str = ""


def _event(
    session: Session,
    event_type: str,
    status: str,
    message: str = "",
    source_id: str | None = None,
    version_id: str | None = None,
) -> None:
    session.add(
        IngestionEvent(
            source_id=source_id,
            version_id=version_id,
            event_type=event_type,
            status=status,
            message=message[:4000],
        )
    )


class IngestionService:
    def __init__(self, session: Session, settings: Settings, embedder: Embedder) -> None:
        self.session = session
        self.settings = settings
        self.embedder = embedder

    # -- sources ------------------------------------------------------------------------------
    def get_source(self, source_key: str) -> LegalSource | None:
        return self.session.scalar(select(LegalSource).where(LegalSource.source_key == source_key))

    def register(self, spec: SourceSpec) -> LegalSource:
        data = spec.model_dump(mode="python")
        data["source_url"] = str(spec.source_url)
        source = self.get_source(spec.source_key)
        if source is None:
            source = LegalSource(**data, verification_status="unverified", is_available=True)
            self.session.add(source)
            self.session.flush()
            _event(self.session, "source_registered", "ok", spec.title, source_id=source.id)
        else:
            changed = [k for k, v in data.items() if getattr(source, k) != v]
            for k in changed:
                setattr(source, k, data[k])
            if changed:
                # Metadata changed: a previous advocate review no longer covers it.
                if source.verification_status == "reviewer_verified":
                    source.verification_status = "fetched_unreviewed" if source.versions else "unverified"
                    source.reviewed_by = None
                _event(
                    self.session,
                    "source_updated",
                    "ok",
                    "changed: " + ", ".join(changed),
                    source_id=source.id,
                )
        return source

    def set_status(
        self,
        source_key: str,
        legal_status: LegalStatus,
        note: str | None = None,
        superseded_by: str | None = None,
        available: bool | None = None,
    ) -> LegalSource:
        source = self._require(source_key)
        source.legal_status = legal_status
        source.status_note = note
        if superseded_by:
            source.superseded_by_id = self._require(superseded_by).id
        if available is not None:
            source.is_available = available
        _event(
            self.session,
            "status_changed",
            "ok",
            f"legal_status={legal_status} available={source.is_available} note={note or ''}",
            source_id=source.id,
        )
        return source

    def mark_reviewed(self, source_key: str, reviewer: str) -> LegalSource:
        source = self._require(source_key)
        if not any(v.is_current for v in source.versions):
            raise ValueError("cannot mark a source as reviewed before a current version is ingested")
        source.verification_status = "reviewer_verified"
        source.reviewed_by = reviewer
        _event(self.session, "reviewed", "ok", f"reviewed by {reviewer}", source_id=source.id)
        return source

    def _require(self, source_key: str) -> LegalSource:
        source = self.get_source(source_key)
        if source is None:
            raise KeyError(f"unknown source {source_key}")
        return source

    # -- versions -----------------------------------------------------------------------------
    def ingest_bytes(
        self,
        source: LegalSource,
        data: bytes,
        declared_mime: str | None = None,
        fetched_url: str | None = None,
    ) -> IngestOutcome:
        max_bytes = self.settings.ingest_max_file_mb * 1024 * 1024
        if not data:
            return self._fail(source, None, "empty document")
        if len(data) > max_bytes:
            return self._fail(source, None, f"document exceeds {self.settings.ingest_max_file_mb} MB")
        try:
            mime = sniff_mime(data, declared_mime)
        except ExtractionError as exc:
            return self._fail(source, None, str(exc))
        digest = hashlib.sha256(data).hexdigest()
        existing = self.session.scalar(
            select(DocumentVersion).where(
                DocumentVersion.source_id == source.id, DocumentVersion.content_hash == digest
            )
        )
        if existing is not None:
            _event(
                self.session,
                "duplicate_skipped",
                "ok",
                f"content hash {digest[:12]} already ingested",
                source_id=source.id,
                version_id=existing.id,
            )
            return IngestOutcome(
                source_key=source.source_key,
                version_id=existing.id,
                status="duplicate",
                passages=len(existing.passages),
                message="identical content already ingested",
            )
        version_no = (
            self.session.scalar(
                select(func.max(DocumentVersion.version_no)).where(DocumentVersion.source_id == source.id)
            )
            or 0
        ) + 1
        stored = None
        if self.settings.keep_raw_source_files:
            stored = f"{digest}{'.pdf' if mime == 'application/pdf' else '.txt'}"
            path = self._storage_path(source.id, stored)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        version = DocumentVersion(
            source_id=source.id,
            version_no=version_no,
            content_hash=digest,
            fetched_url=fetched_url,
            stored_file=stored,
            mime_type=mime,
            byte_size=len(data),
            extraction_status="pending",
            extraction_notes=[],
            is_current=False,
        )
        self.session.add(version)
        self.session.flush()
        return self._process(source, version, data)

    def reprocess(self, version_id: str) -> IngestOutcome:
        version = self.session.get(DocumentVersion, version_id)
        if version is None:
            raise KeyError(f"unknown version {version_id}")
        if not version.stored_file:
            raise ValueError("raw file was not retained (KEEP_RAW_SOURCE_FILES=false); re-ingest instead")
        data = self._storage_path(version.source_id, version.stored_file).read_bytes()
        if hashlib.sha256(data).hexdigest() != version.content_hash:
            raise ValueError("stored file does not match recorded content hash")
        for p in list(version.passages):
            self.session.delete(p)
        self.session.flush()
        return self._process(version.source, version, data)

    def _storage_path(self, source_id: str, stored_file: str) -> Path:
        base = self.settings.uploads_dir.resolve()
        path = (base / source_id / stored_file).resolve()
        if base not in path.parents:
            raise ValueError("unsafe storage path")
        return path

    def _process(self, source: LegalSource, version: DocumentVersion, data: bytes) -> IngestOutcome:
        try:
            doc = extract(data, version.mime_type)
        except ExtractionError as exc:
            version.extraction_status = "failed"
            version.extraction_error = str(exc)
            return self._fail(source, version, str(exc))
        segments, strategy = segment(doc, source.document_type)
        notes = list(doc.notes) + [f"segmentation={strategy}"]
        if strategy == "numbered":
            notes.append("paragraph/section labels derived heuristically from numbering; verify against page")
        embeddings = self.embedder.embed([s.text for s in segments]) if segments else []
        flagged = 0
        for i, (seg, emb) in enumerate(zip(segments, embeddings, strict=True)):
            flags = []
            if looks_like_injection(seg.text):
                flags.append("suspected_instructions")
                flagged += 1
            self.session.add(
                Passage(
                    version_id=version.id,
                    source_id=source.id,
                    ordinal=i,
                    page_start=seg.page_start,
                    page_end=seg.page_end,
                    section_label=seg.label,
                    locator=seg.locator,
                    text=seg.text,
                    text_hash=sha256_text(seg.text),
                    language=seg.language,
                    flags=flags,
                    embedding=emb,
                )
            )
        if flagged:
            notes.append(
                f"{flagged} passage(s) flagged as containing instruction-like text; excluded from answers"
            )
        version.extraction_status = "succeeded"
        if any("little or no extractable text" in n for n in doc.notes):
            version.extraction_status = "partial"
        version.extraction_notes = notes
        version.page_count = len(doc.pages) if doc.paginated else None
        version.char_count = doc.char_count
        for other in source.versions:
            if other.id != version.id:
                other.is_current = False
        version.is_current = True
        if source.verification_status == "unverified":
            source.verification_status = "fetched_unreviewed"
        source.updated_at = utcnow()
        _event(
            self.session,
            "version_ingested",
            "ok",
            f"v{version.version_no}: {len(segments)} passages; " + "; ".join(notes),
            source_id=source.id,
            version_id=version.id,
        )
        return IngestOutcome(
            source_key=source.source_key,
            version_id=version.id,
            status="created",
            passages=len(segments),
            message="; ".join(notes),
        )

    def _fail(self, source: LegalSource, version: DocumentVersion | None, message: str) -> IngestOutcome:
        _event(
            self.session,
            "ingest_failed",
            "error",
            message,
            source_id=source.id,
            version_id=version.id if version else None,
        )
        log.warning("ingestion failed for %s: %s", source.source_key, message)
        return IngestOutcome(
            source_key=source.source_key,
            version_id=version.id if version else None,
            status="failed",
            message=message,
        )

    def record_error(self, source: LegalSource, message: str) -> IngestOutcome:
        return self._fail(source, None, message)

    # -- provenance --------------------------------------------------------------------------
    def provenance(self, passage_id: str) -> dict[str, Any]:
        passage = self.session.get(Passage, passage_id)
        if passage is None:
            raise KeyError(f"unknown passage {passage_id}")
        version, source = passage.version, passage.source
        return {
            "passage": {
                "id": passage.id,
                "ordinal": passage.ordinal,
                "locator": passage.locator,
                "page_start": passage.page_start,
                "page_end": passage.page_end,
                "section_label": passage.section_label,
                "language": passage.language,
                "flags": passage.flags,
                "text_sha256": passage.text_hash,
                "text": passage.text,
            },
            "version": {
                "id": version.id,
                "version_no": version.version_no,
                "content_sha256": version.content_hash,
                "retrieved_at": version.retrieved_at.isoformat(),
                "fetched_url": version.fetched_url,
                "is_current": version.is_current,
                "extraction_status": version.extraction_status,
                "extraction_notes": version.extraction_notes,
            },
            "source": {
                "id": source.id,
                "source_key": source.source_key,
                "title": source.title,
                "source_url": source.source_url,
                "document_type": source.document_type,
                "source_category": source.source_category,
                "jurisdiction": source.jurisdiction,
                "legal_status": source.legal_status,
                "verification_status": source.verification_status,
                "reviewed_by": source.reviewed_by,
                "host_note": source.host_note,
                "publication_date": _iso(source.publication_date),
                "commencement_date": _iso(source.commencement_date),
                "judgment_date": _iso(source.judgment_date),
            },
        }


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None
