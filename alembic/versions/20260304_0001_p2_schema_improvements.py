"""P2 schema improvements: cost_usd precision, pending_delete JSONB, practice_logs index

Revision ID: 20260304_0001
Revises: 20260220_0002
Create Date: 2026-03-04

- api_usage_logs.cost_usd: Float → Numeric(10,6)（避免浮點精度問題）
- user_states.pending_delete_items: Text → JSONB（原本以 JSON string 存放）
- practice_logs: 新增 item_id 單獨索引（加速 item→log 反查）
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260304_0001"
down_revision = "20260220_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- #19: cost_usd Float → Numeric(10,6) ---
    op.alter_column(
        "api_usage_logs",
        "cost_usd",
        existing_type=sa.Float(),
        type_=sa.Numeric(10, 6),
        existing_nullable=False,
        existing_server_default=None,
    )

    # --- #20: pending_delete_items Text → JSONB ---
    # 先用 USING 轉換現有 JSON string 為 JSONB
    op.execute(
        "ALTER TABLE user_states "
        "ALTER COLUMN pending_delete_items TYPE JSONB "
        "USING pending_delete_items::jsonb"
    )

    # --- #21: practice_logs.item_id 單獨索引 ---
    op.create_index(
        "idx_practice_logs_item_id",
        "practice_logs",
        ["item_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_practice_logs_item_id", table_name="practice_logs")

    op.execute(
        "ALTER TABLE user_states "
        "ALTER COLUMN pending_delete_items TYPE TEXT "
        "USING pending_delete_items::text"
    )

    op.alter_column(
        "api_usage_logs",
        "cost_usd",
        existing_type=sa.Numeric(10, 6),
        type_=sa.Float(),
        existing_nullable=False,
    )
