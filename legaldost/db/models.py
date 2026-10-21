"""Relational schema for legal sources, versions, passages, conversations and diagnostics.

Dates that describe the law (publication, commencement, judgment) are kept in separate nullable
columns. NULL means *unknown*; nothing is inferred from file names.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from legaldost.db.types import EmbeddingVector


def _uuid() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[str]: JSON}


class LegalSource(Base):
    __tablename__ = "legal_sources"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    source_key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(500))
    issuing_authority: Mapped[str] = mapped_column(String(300))
    document_type: Mapped[str] = mapped_column(String(40))
    source_category: Mapped[str] = mapped_column(String(40))
    jurisdiction: Mapped[str] = mapped_column(String(20), index=True)
    court_level: Mapped[str | None] = mapped_column(String(40), nullable=True)
    legal_domains: Mapped[list[str]] = mapped_column(JSON, default=list)
    identifiers: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_url: Mapped[str] = mapped_column(String(1000))
    host_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    languages: Mapped[list[str]] = mapped_column(JSON, default=list)
    publication_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    commencement_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    judgment_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    legal_status: Mapped[str] = mapped_column(String(30), default="unknown")
    status_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    verification_status: Mapped[str] = mapped_column(String(30), default="unverified")
    reviewed_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    licensing_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
    superseded_by_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("legal_sources.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    versions: Mapped[list[DocumentVersion]] = relationship(
        back_populates="source", order_by="DocumentVersion.version_no"
    )


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("source_id", "content_hash", name="uq_version_source_hash"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    source_id: Mapped[str] = mapped_column(String(32), ForeignKey("legal_sources.id"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    fetched_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    stored_file: Mapped[str | None] = mapped_column(String(200), nullable=True)
    mime_type: Mapped[str] = mapped_column(String(80))
    byte_size: Mapped[int] = mapped_column(Integer)
    extraction_status: Mapped[str] = mapped_column(String(20), default="pending")
    extraction_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_notes: Mapped[list[str]] = mapped_column(JSON, default=list)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    source: Mapped[LegalSource] = relationship(back_populates="versions")
    passages: Mapped[list[Passage]] = relationship(back_populates="version", cascade="all, delete-orphan")


class Passage(Base):
    __tablename__ = "passages"
    __table_args__ = (Index("ix_passages_source_version", "source_id", "version_id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    version_id: Mapped[str] = mapped_column(String(32), ForeignKey("document_versions.id"), index=True)
    source_id: Mapped[str] = mapped_column(String(32), ForeignKey("legal_sources.id"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section_label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    locator: Mapped[str] = mapped_column(String(120))
    text: Mapped[str] = mapped_column(Text)
    text_hash: Mapped[str] = mapped_column(String(64))
    language: Mapped[str] = mapped_column(String(10), default="en")
    flags: Mapped[list[str]] = mapped_column(JSON, default=list)
    embedding: Mapped[list[float] | None] = mapped_column(EmbeddingVector(), nullable=True)

    version: Mapped[DocumentVersion] = relationship(back_populates="passages")
    source: Mapped[LegalSource] = relationship()


class IngestionEvent(Base):
    __tablename__ = "ingestion_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    source_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("legal_sources.id"), nullable=True)
    version_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    event_type: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (UniqueConstraint("channel", "user_key", name="uq_conversation_user"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    channel: Mapped[str] = mapped_column(String(20))
    user_key: Mapped[str] = mapped_column(String(64))
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    topic: Mapped[str | None] = mapped_column(String(80), nullable=True)
    facts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    pending_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_answer: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    notice_shown: Mapped[bool] = mapped_column(Boolean, default=False)
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ProcessedEvent(Base):
    __tablename__ = "processed_events"

    event_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    channel: Mapped[str] = mapped_column(String(20))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class UsageRecord(Base):
    __tablename__ = "usage_records"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(80))
    purpose: Mapped[str] = mapped_column(String(40))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class AnswerLog(Base):
    """Diagnostic metadata only. Never stores message text or user identifiers."""

    __tablename__ = "answer_logs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    channel: Mapped[str] = mapped_column(String(20))
    outcome: Mapped[str] = mapped_column(String(30))
    intent: Mapped[str | None] = mapped_column(String(40), nullable=True)
    domain: Mapped[str | None] = mapped_column(String(40), nullable=True)
    topic: Mapped[str | None] = mapped_column(String(80), nullable=True)
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    evidence_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    passages_retrieved: Mapped[int] = mapped_column(Integer, default=0)
    citations_shown: Mapped[int] = mapped_column(Integer, default=0)
    validator_flags: Mapped[list[str]] = mapped_column(JSON, default=list)
    llm_calls: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
