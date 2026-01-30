"""add practice_sessions and user_states

Revision ID: 7b489b2e68d0
Revises: 20260129_0005
Create Date: 2026-01-30 03:11:50.025986+00:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "7b489b2e68d0"
down_revision: Union[str, None] = "20260129_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "practice_sessions",
        sa.Column("session_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column(
            "user_id",
            sa.String(length=64),
            nullable=False,
            comment="Hashed LINE user ID",
        ),
        sa.Column(
            "state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="PracticeSession.model_dump() snapshot",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="Session 過期時間",
        ),
        sa.Column(
            "is_deleted", sa.Boolean(), nullable=False, server_default=sa.false(), comment="Soft delete flag"
        ),
        sa.PrimaryKeyConstraint("session_id"),
    )
    op.create_index(
        op.f("ix_practice_sessions_user_id"),
        "practice_sessions",
        ["user_id"],
        unique=False,
    )
    op.create_table(
        "user_states",
        sa.Column(
            "user_id",
            sa.String(length=64),
            nullable=False,
            comment="Hashed LINE user ID",
        ),
        sa.Column(
            "last_message", sa.Text(), nullable=True, comment="最後一則非指令訊息"
        ),
        sa.Column(
            "last_message_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="最後訊息時間",
        ),
        sa.Column(
            "delete_confirm_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="清空資料確認請求時間",
        ),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("user_states")
    op.drop_index(op.f("ix_practice_sessions_user_id"), table_name="practice_sessions")
    op.drop_table("practice_sessions")
