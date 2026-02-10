"""add is_deleted to user_profiles

Revision ID: 20260211_0001
Revises: 20260210_0001
Create Date: 2026-02-11
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260211_0001"
down_revision = "20260210_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_profiles",
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            comment="Soft delete flag",
        ),
    )


def downgrade() -> None:
    op.drop_column("user_profiles", "is_deleted")
