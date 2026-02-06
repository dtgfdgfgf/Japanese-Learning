"""add pending_delete to user_states

Revision ID: 20260207_0001
Revises: 20260204_0001
Create Date: 2026-02-07
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260207_0001"
down_revision = "20260204_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_states",
        sa.Column(
            "pending_delete_items",
            sa.Text(),
            nullable=True,
            comment="待確認刪除的項目列表（JSON）",
        ),
    )
    op.add_column(
        "user_states",
        sa.Column(
            "pending_delete_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="待確認刪除設定時間",
        ),
    )


def downgrade() -> None:
    op.drop_column("user_states", "pending_delete_at")
    op.drop_column("user_states", "pending_delete_items")
