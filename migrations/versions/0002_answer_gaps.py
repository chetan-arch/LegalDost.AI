"""Gap log: questions the assistant could not answer (keywords only, no message text).

Revision ID: 0002_answer_gaps
Revises: 0001_initial
Create Date: 2026-10-21
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_answer_gaps"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "answer_gaps",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("outcome", sa.String(30), nullable=False),
        sa.Column("reason", sa.String(60), nullable=False),
        sa.Column("topic", sa.String(80)),
        sa.Column("domain", sa.String(40)),
        sa.Column("terms", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_answer_gaps_created_at", "answer_gaps", ["created_at"])
    op.create_index("ix_answer_gaps_expires_at", "answer_gaps", ["expires_at"])


def downgrade() -> None:
    op.drop_table("answer_gaps")
