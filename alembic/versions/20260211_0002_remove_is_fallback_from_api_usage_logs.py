"""remove is_fallback from api_usage_logs

Revision ID: 20260211_0002
Revises: 20260211_0001
Create Date: 2026-02-11
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260211_0002"
down_revision = "20260211_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("api_usage_logs", "is_fallback")


def downgrade() -> None:
    op.add_column(
        "api_usage_logs",
        sa.Column(
            "is_fallback",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            comment="Whether this was a fallback call",
        ),
    )
