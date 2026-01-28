"""Initial migration - Create all base tables.

Revision ID: 20260127_0001_initial
Revises: 
Create Date: 2026-01-27

T013: Create Alembic migration for all tables
DoD: alembic upgrade head 成功建立 4 張表
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260127_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create raw_messages table
    op.create_table(
        "raw_messages",
        sa.Column("raw_id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False, index=True),
        sa.Column("channel", sa.String(32), nullable=False, server_default="line"),
        sa.Column("raw_text", sa.Text, nullable=False),
        sa.Column("raw_meta", postgresql.JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "is_deleted", sa.Boolean, nullable=False, server_default=sa.text("false")
        ),
    )

    # Create index for raw_messages
    op.create_index(
        "idx_raw_messages_user_created",
        "raw_messages",
        ["user_id", sa.text("created_at DESC")],
    )

    # Create documents table
    op.create_table(
        "documents",
        sa.Column("doc_id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "raw_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("raw_messages.raw_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(64), nullable=False, index=True),
        sa.Column("lang", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("doc_type", sa.String(16), nullable=False, server_default="text"),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column(
            "tags", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'")
        ),
        sa.Column(
            "parse_status", sa.String(16), nullable=False, server_default="deferred"
        ),
        sa.Column("parser_version", sa.String(32), nullable=True),
        sa.Column("llm_trace", postgresql.JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # Create index for documents
    op.create_index(
        "idx_documents_user_created",
        "documents",
        ["user_id", sa.text("created_at DESC")],
    )

    # Create items table
    op.create_table(
        "items",
        sa.Column("item_id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False, index=True),
        sa.Column(
            "doc_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("documents.doc_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("item_type", sa.String(16), nullable=False),
        sa.Column("key", sa.String(256), nullable=False, index=True),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("source_quote", sa.Text, nullable=True),
        sa.Column("confidence", sa.Float, nullable=False, server_default=sa.text("1.0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "is_deleted", sa.Boolean, nullable=False, server_default=sa.text("false")
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_items_confidence_range"
        ),
    )

    # Create unique constraint for items (with partial index for non-deleted)
    op.create_index(
        "uq_items_user_type_key",
        "items",
        ["user_id", "item_type", "key"],
        unique=True,
        postgresql_where=sa.text("is_deleted = false"),
    )

    # Create practice_logs table
    op.create_table(
        "practice_logs",
        sa.Column("log_id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False, index=True),
        sa.Column(
            "item_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("items.item_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("practice_type", sa.String(32), nullable=False),
        sa.Column("prompt_snapshot", sa.Text, nullable=True),
        sa.Column("user_answer", sa.Text, nullable=False),
        sa.Column("is_correct", sa.Boolean, nullable=False),
        sa.Column("score", sa.Float, nullable=True),
        sa.Column("feedback", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # Create indexes for practice_logs
    op.create_index(
        "idx_practice_logs_user_created",
        "practice_logs",
        ["user_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "idx_practice_logs_user_item_created",
        "practice_logs",
        ["user_id", "item_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    # Drop tables in reverse order (due to foreign keys)
    op.drop_table("practice_logs")
    op.drop_table("items")
    op.drop_table("documents")
    op.drop_table("raw_messages")
