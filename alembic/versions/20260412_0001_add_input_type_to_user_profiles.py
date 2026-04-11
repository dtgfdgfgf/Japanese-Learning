"""add input_type to user_profiles

Revision ID: 20260412_0001
Revises: 9edcc004a997
Create Date: 2026-04-12
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260412_0001"
down_revision = "9edcc004a997"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_profiles",
        sa.Column(
            "input_type",
            sa.String(16),
            nullable=False,
            server_default="query",
            comment="Input routing: query/ask",
        ),
    )


def downgrade() -> None:
    op.drop_column("user_profiles", "input_type")
