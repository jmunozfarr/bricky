"""Create rebrickable_sets, rebrickable_set_parts, rebrickable_set_data_state.

Rebuildable Rebrickable set catalog and per-set official parts list,
populated by `python -m app.cli.rebrickable_mapping populate-sets` from the
public Rebrickable data dumps (no API key). Classified like the catalog:
droppable and rebuildable, never referenced by personal rows.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260716_10"
down_revision: str | None = "20260716_09"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rebrickable_sets",
        sa.Column("set_num", sa.String(length=32), primary_key=True),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("num_parts", sa.Integer(), nullable=False),
        sa.Column("chosen_version", sa.Integer(), nullable=False),
    )

    op.create_table(
        "rebrickable_set_parts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("set_num", sa.String(length=32), nullable=False),
        sa.Column("part_num", sa.String(length=64), nullable=False),
        sa.Column("color_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("is_spare", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_rebrickable_set_parts_set_num", "rebrickable_set_parts", ["set_num"])

    op.create_table(
        "rebrickable_set_data_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("populated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("set_count", sa.Integer(), nullable=False),
        sa.Column("part_row_count", sa.Integer(), nullable=False),
        sa.Column("fetcher_version", sa.String(length=32), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("rebrickable_set_data_state")
    op.drop_index("ix_rebrickable_set_parts_set_num", table_name="rebrickable_set_parts")
    op.drop_table("rebrickable_set_parts")
    op.drop_table("rebrickable_sets")
