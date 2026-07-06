"""Functional indexes matching the case-insensitive part-id lookups.

Catalog joins and scoped manifest queries filter on lower(part_id); the
inventory lookups filter on (lower(btrim(part_id)), color_code).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260706_05"
down_revision: str | None = "20260706_04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_parts_lower_part_id",
        "parts",
        [sa.text("lower(part_id)")],
    )
    op.create_index(
        "ix_model_bom_items_lower_part_id",
        "model_bom_items",
        [sa.text("lower(part_id)")],
    )
    op.create_index(
        "ix_inventory_items_lower_trim_part_id_color",
        "inventory_items",
        [sa.text("lower(btrim(part_id))"), sa.text("color_code")],
    )


def downgrade() -> None:
    op.drop_index("ix_inventory_items_lower_trim_part_id_color", table_name="inventory_items")
    op.drop_index("ix_model_bom_items_lower_part_id", table_name="model_bom_items")
    op.drop_index("ix_parts_lower_part_id", table_name="parts")
