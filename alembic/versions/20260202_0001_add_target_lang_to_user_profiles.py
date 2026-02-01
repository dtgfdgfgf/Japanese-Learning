"""add target_lang to user_profiles

Revision ID: 20260202_0001
Revises: 20260130_0400_add_practice_logs_is_deleted
Create Date: 2026-02-02
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260202_0001"
down_revision = "20260130_0400_add_practice_logs_is_deleted"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_profiles",
        sa.Column(
            "target_lang",
            sa.String(5),
            nullable=False,
            server_default="ja",
            comment="目標學習語言: ja/en",
        ),
    )


def downgrade() -> None:
    op.drop_column("user_profiles", "target_lang")
