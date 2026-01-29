"""Add api_usage_logs table.

Revision ID: 20260129_0003
Revises: 20260129_0002
Create Date: 2026-01-29

新增 API 用量記錄資料表，用於追蹤 LLM API 呼叫的 token 使用量與費用。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260129_0003"
down_revision: Union[str, None] = "20260129_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 建立 api_usage_logs 資料表
    op.create_table(
        "api_usage_logs",
        sa.Column(
            "log_id",
            postgresql.UUID(as_uuid=False),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            sa.String(64),
            nullable=False,
            comment="Hashed LINE user ID",
        ),
        sa.Column(
            "provider",
            sa.String(16),
            nullable=False,
            comment="LLM provider: anthropic, openai",
        ),
        sa.Column(
            "model",
            sa.String(64),
            nullable=False,
            comment="Model name",
        ),
        sa.Column(
            "operation",
            sa.String(32),
            nullable=False,
            comment="Operation type: extraction, practice, router",
        ),
        sa.Column(
            "input_tokens",
            sa.Integer,
            nullable=False,
            default=0,
            comment="Input token count",
        ),
        sa.Column(
            "output_tokens",
            sa.Integer,
            nullable=False,
            default=0,
            comment="Output token count",
        ),
        sa.Column(
            "cost_usd",
            sa.Float,
            nullable=False,
            default=0.0,
            comment="Calculated cost in USD",
        ),
        sa.Column(
            "latency_ms",
            sa.Integer,
            nullable=False,
            default=0,
            comment="API response latency in milliseconds",
        ),
        sa.Column(
            "is_fallback",
            sa.Boolean,
            nullable=False,
            default=False,
            comment="Whether this was a fallback call",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="Creation timestamp",
        ),
    )

    # 建立索引以加速查詢
    op.create_index(
        "ix_api_usage_logs_user_id",
        "api_usage_logs",
        ["user_id"],
    )
    op.create_index(
        "ix_api_usage_logs_created_at",
        "api_usage_logs",
        ["created_at"],
    )
    op.create_index(
        "ix_api_usage_logs_user_created",
        "api_usage_logs",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    # 移除索引
    op.drop_index("ix_api_usage_logs_user_created", table_name="api_usage_logs")
    op.drop_index("ix_api_usage_logs_created_at", table_name="api_usage_logs")
    op.drop_index("ix_api_usage_logs_user_id", table_name="api_usage_logs")

    # 移除資料表
    op.drop_table("api_usage_logs")
