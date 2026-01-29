"""migrate mode 'balanced' to 'free' and update server_default

Revision ID: 20260129_0005
Revises: 20260129_0004
Create Date: 2026-01-29
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260129_0005"
down_revision = "20260129_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 將既有 balanced 模式的使用者遷移為 free
    op.execute("UPDATE user_profiles SET mode = 'free' WHERE mode = 'balanced'")

    # 更新 server_default
    op.alter_column(
        "user_profiles",
        "mode",
        server_default="free",
        comment="LLM mode: free/cheap/rigorous",
    )


def downgrade() -> None:
    # 還原 server_default
    op.alter_column(
        "user_profiles",
        "mode",
        server_default="balanced",
        comment="LLM mode: cheap/balanced/rigorous",
    )

    # 將 free 模式的使用者還原為 balanced
    op.execute("UPDATE user_profiles SET mode = 'balanced' WHERE mode = 'free'")
