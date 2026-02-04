"""add pending_save to user_states

Revision ID: 20260204_0001
Revises: 20260202_0001
Create Date: 2026-02-04
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260204_0001"
down_revision = "20260202_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_states",
        sa.Column(
            "pending_save_content",
            sa.Text(),
            nullable=True,
            comment="待確認入庫的內容",
        ),
    )
    op.add_column(
        "user_states",
        sa.Column(
            "pending_save_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="待確認入庫設定時間",
        ),
    )


def downgrade() -> None:
    op.drop_column("user_states", "pending_save_at")
    op.drop_column("user_states", "pending_save_content")
