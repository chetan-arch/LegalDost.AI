"""Initial schema: sources, versions, passages, conversations, diagnostics.

On PostgreSQL this also enables pgvector, stores embeddings as vector(n), and adds a generated
tsvector column with a GIN index for full-text search.

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def _ts(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    if is_pg:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "legal_sources",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("source_key", sa.String(120), nullable=False, unique=True, index=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("issuing_authority", sa.String(300), nullable=False),
        sa.Column("document_type", sa.String(40), nullable=False),
        sa.Column("source_category", sa.String(40), nullable=False),
        sa.Column("jurisdiction", sa.String(20), nullable=False, index=True),
        sa.Column("court_level", sa.String(40)),
        sa.Column("legal_domains", sa.JSON, nullable=False),
        sa.Column("identifiers", sa.JSON, nullable=False),
        sa.Column("source_url", sa.String(1000), nullable=False),
        sa.Column("host_note", sa.Text),
        sa.Column("languages", sa.JSON, nullable=False),
        sa.Column("publication_date", sa.Date),
        sa.Column("commencement_date", sa.Date),
        sa.Column("judgment_date", sa.Date),
        sa.Column("legal_status", sa.String(30), nullable=False),
        sa.Column("status_note", sa.Text),
        sa.Column("verification_status", sa.String(30), nullable=False),
        sa.Column("reviewed_by", sa.String(200)),
        sa.Column("licensing_note", sa.Text),
        sa.Column("is_available", sa.Boolean, nullable=False),
        sa.Column("superseded_by_id", sa.String(32), sa.ForeignKey("legal_sources.id")),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_table(
        "document_versions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("source_id", sa.String(32), sa.ForeignKey("legal_sources.id"), nullable=False, index=True),
        sa.Column("version_no", sa.Integer, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False, index=True),
        _ts("retrieved_at"),
        sa.Column("fetched_url", sa.String(1000)),
        sa.Column("stored_file", sa.String(200)),
        sa.Column("mime_type", sa.String(80), nullable=False),
        sa.Column("byte_size", sa.Integer, nullable=False),
        sa.Column("extraction_status", sa.String(20), nullable=False),
        sa.Column("extraction_error", sa.Text),
        sa.Column("extraction_notes", sa.JSON, nullable=False),
        sa.Column("page_count", sa.Integer),
        sa.Column("char_count", sa.Integer),
        sa.Column("is_current", sa.Boolean, nullable=False),
        _ts("created_at"),
        sa.UniqueConstraint("source_id", "content_hash", name="uq_version_source_hash"),
    )
    embedding_type: sa.types.TypeEngine = sa.JSON()
    if is_pg:
        from pgvector.sqlalchemy import Vector

        from legaldost.config import get_settings

        embedding_type = Vector(get_settings().embedding_dim)
    op.create_table(
        "passages",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "version_id", sa.String(32), sa.ForeignKey("document_versions.id"), nullable=False, index=True
        ),
        sa.Column("source_id", sa.String(32), sa.ForeignKey("legal_sources.id"), nullable=False, index=True),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("page_start", sa.Integer),
        sa.Column("page_end", sa.Integer),
        sa.Column("section_label", sa.String(80)),
        sa.Column("locator", sa.String(120), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("text_hash", sa.String(64), nullable=False),
        sa.Column("language", sa.String(10), nullable=False),
        sa.Column("flags", sa.JSON, nullable=False),
        sa.Column("embedding", embedding_type),
    )
    op.create_index("ix_passages_source_version", "passages", ["source_id", "version_id"])
    if is_pg:
        op.execute(
            "ALTER TABLE passages ADD COLUMN tsv tsvector "
            "GENERATED ALWAYS AS (to_tsvector('english', coalesce(section_label,'') || ' ' || text)) STORED"
        )
        op.execute("CREATE INDEX ix_passages_tsv ON passages USING GIN (tsv)")
        op.execute("CREATE INDEX ix_passages_embedding ON passages USING hnsw (embedding vector_cosine_ops)")

    op.create_table(
        "ingestion_events",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("source_id", sa.String(32), sa.ForeignKey("legal_sources.id")),
        sa.Column("version_id", sa.String(32)),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        _ts("created_at"),
    )
    op.create_index("ix_ingestion_events_created_at", "ingestion_events", ["created_at"])
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("user_key", sa.String(64), nullable=False),
        sa.Column("language", sa.String(10)),
        sa.Column("topic", sa.String(80)),
        sa.Column("facts", sa.JSON, nullable=False),
        sa.Column("pending_question", sa.Text),
        sa.Column("last_answer", sa.JSON),
        sa.Column("notice_shown", sa.Boolean, nullable=False),
        _ts("last_inbound_at", nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        _ts("expires_at"),
        sa.UniqueConstraint("channel", "user_key", name="uq_conversation_user"),
    )
    op.create_index("ix_conversations_expires_at", "conversations", ["expires_at"])
    op.create_table(
        "processed_events",
        sa.Column("event_id", sa.String(200), primary_key=True),
        sa.Column("channel", sa.String(20), nullable=False),
        _ts("received_at"),
    )
    op.create_index("ix_processed_events_received_at", "processed_events", ["received_at"])
    op.create_table(
        "usage_records",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("model", sa.String(80), nullable=False),
        sa.Column("purpose", sa.String(40), nullable=False),
        sa.Column("input_tokens", sa.Integer, nullable=False),
        sa.Column("output_tokens", sa.Integer, nullable=False),
        sa.Column("cost_usd", sa.Float, nullable=False),
        sa.Column("latency_ms", sa.Integer, nullable=False),
        sa.Column("success", sa.Boolean, nullable=False),
        sa.Column("error_type", sa.String(80)),
        _ts("created_at"),
    )
    op.create_index("ix_usage_records_created_at", "usage_records", ["created_at"])
    op.create_table(
        "answer_logs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("outcome", sa.String(30), nullable=False),
        sa.Column("intent", sa.String(40)),
        sa.Column("domain", sa.String(40)),
        sa.Column("topic", sa.String(80)),
        sa.Column("language", sa.String(10)),
        sa.Column("evidence_status", sa.String(40)),
        sa.Column("passages_retrieved", sa.Integer, nullable=False),
        sa.Column("citations_shown", sa.Integer, nullable=False),
        sa.Column("validator_flags", sa.JSON, nullable=False),
        sa.Column("llm_calls", sa.Integer, nullable=False),
        sa.Column("latency_ms", sa.Integer, nullable=False),
        _ts("created_at"),
    )
    op.create_index("ix_answer_logs_created_at", "answer_logs", ["created_at"])


def downgrade() -> None:
    for table in (
        "answer_logs",
        "usage_records",
        "processed_events",
        "conversations",
        "ingestion_events",
        "passages",
        "document_versions",
        "legal_sources",
    ):
        op.drop_table(table)
