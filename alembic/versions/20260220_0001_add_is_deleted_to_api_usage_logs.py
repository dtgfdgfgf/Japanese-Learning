"""add is_deleted to api_usage_logs

Revision ID: 20260220_0001
Revises: 20260211_0002
Create Date: 2026-02-20

api_usage_logs 表缺少 is_deleted 欄位，導致 soft-delete 過濾查詢失敗。
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260220_0001"
down_revision = "20260211_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "api_usage_logs",
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            comment="Soft delete flag",
        ),
    )


def downgrade() -> None:
    op.drop_column("api_usage_logs", "is_deleted")
