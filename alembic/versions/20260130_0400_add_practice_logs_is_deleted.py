"""add practice_logs is_deleted column

Revision ID: a1b2c3d4e5f6
Revises: 7b489b2e68d0
Create Date: 2026-01-30 04:00:00.000000+00:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "7b489b2e68d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "practice_logs",
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            comment="Soft delete flag",
        ),
    )


def downgrade() -> None:
    op.drop_column("practice_logs", "is_deleted")
