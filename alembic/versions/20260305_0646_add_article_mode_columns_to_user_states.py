"""add article mode columns to user_states

Revision ID: 9edcc004a997
Revises: 20260304_0001
Create Date: 2026-03-05 06:46:40.564780+00:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "9edcc004a997"
down_revision: Union[str, None] = "20260304_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_states",
        sa.Column(
            "article_mode_text",
            sa.Text(),
            nullable=True,
            comment="文章閱讀模式原文（供查詞語境）",
        ),
    )
    op.add_column(
        "user_states",
        sa.Column(
            "article_mode_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="進入文章閱讀模式時間",
        ),
    )


def downgrade() -> None:
    op.drop_column("user_states", "article_mode_at")
    op.drop_column("user_states", "article_mode_text")
