"""add user_profiles table

Revision ID: 20260129_0004
Revises: 20260129_0003_add_api_usage_logs_table
Create Date: 2026-01-29
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260129_0004"
down_revision = "20260129_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_profiles",
        sa.Column("user_id", sa.String(64), primary_key=True, comment="Hashed LINE user ID"),
        sa.Column("mode", sa.String(16), nullable=False, server_default="balanced", comment="LLM mode: cheap/balanced/rigorous"),
        sa.Column("daily_cap_tokens_free", sa.Integer(), nullable=False, server_default="50000", comment="Daily free token cap"),
        sa.Column("daily_used_tokens", sa.Integer(), nullable=False, server_default="0", comment="Tokens used today"),
        sa.Column("reset_at", sa.DateTime(timezone=True), nullable=False, comment="Next daily reset time"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("user_profiles")
