"""Add is_deleted column to documents table.

Revision ID: 20260129_0002
Revises: 20260127_0001
Create Date: 2026-01-29

修復：Document model 缺少 soft delete 欄位
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260129_0002"
down_revision: Union[str, None] = "20260127_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add is_deleted column to documents table
    op.add_column(
        "documents",
        sa.Column(
            "is_deleted",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
            comment="Soft delete flag",
        ),
    )


def downgrade() -> None:
    # Remove is_deleted column from documents table
    op.drop_column("documents", "is_deleted")
