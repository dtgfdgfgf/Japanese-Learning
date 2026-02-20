"""align fk ondelete rules to RESTRICT

Revision ID: 20260220_0002
Revises: 20260220_0001
Create Date: 2026-02-20

將初始 migration 的 FK ondelete 設定對齊目前 ORM（RESTRICT）。
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260220_0002"
down_revision = "20260220_0001"
branch_labels = None
depends_on = None


def _recreate_fk_ondelete(
    table_name: str,
    column_name: str,
    referred_table: str,
    referred_column: str,
    ondelete: str,
) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    fk_name = None
    for fk in inspector.get_foreign_keys(table_name):
        if (
            fk.get("constrained_columns") == [column_name]
            and fk.get("referred_table") == referred_table
        ):
            fk_name = fk.get("name")
            break

    if fk_name is None:
        raise RuntimeError(
            f"Foreign key not found: {table_name}.{column_name} -> {referred_table}.{referred_column}"
        )

    op.drop_constraint(fk_name, table_name, type_="foreignkey")
    op.create_foreign_key(
        fk_name,
        table_name,
        referred_table,
        [column_name],
        [referred_column],
        ondelete=ondelete,
    )


def upgrade() -> None:
    _recreate_fk_ondelete(
        table_name="documents",
        column_name="raw_id",
        referred_table="raw_messages",
        referred_column="raw_id",
        ondelete="RESTRICT",
    )
    _recreate_fk_ondelete(
        table_name="items",
        column_name="doc_id",
        referred_table="documents",
        referred_column="doc_id",
        ondelete="RESTRICT",
    )
    _recreate_fk_ondelete(
        table_name="practice_logs",
        column_name="item_id",
        referred_table="items",
        referred_column="item_id",
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    _recreate_fk_ondelete(
        table_name="documents",
        column_name="raw_id",
        referred_table="raw_messages",
        referred_column="raw_id",
        ondelete="CASCADE",
    )
    _recreate_fk_ondelete(
        table_name="items",
        column_name="doc_id",
        referred_table="documents",
        referred_column="doc_id",
        ondelete="CASCADE",
    )
    _recreate_fk_ondelete(
        table_name="practice_logs",
        column_name="item_id",
        referred_table="items",
        referred_column="item_id",
        ondelete="CASCADE",
    )
