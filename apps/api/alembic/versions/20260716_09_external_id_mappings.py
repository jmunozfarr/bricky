"""Create external_part_id_map, external_color_map, external_id_map_state.

Rebuildable Rebrickable/BrickLink -> LDraw cross-reference, populated by
`python -m app.cli.rebrickable_mapping populate`. Classified like the
catalog: droppable and rebuildable, never referenced by personal rows.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260716_09"
down_revision: str | None = "20260711_08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "external_part_id_map",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_system", sa.String(length=16), nullable=False),
        sa.Column("source_part_id", sa.String(length=64), nullable=False),
        sa.Column("ldraw_part_id", sa.String(length=64), nullable=False),
        sa.Column("is_preferred", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint(
            "source_system",
            "source_part_id",
            "ldraw_part_id",
            name="uq_external_part_id_map_candidate",
        ),
        sa.CheckConstraint(
            "source_system IN ('rebrickable', 'bricklink')",
            name="ck_external_part_id_map_source_system",
        ),
    )
    op.create_index(
        "ix_external_part_id_map_lookup",
        "external_part_id_map",
        ["source_system", "source_part_id"],
    )

    op.create_table(
        "external_color_map",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_system", sa.String(length=16), nullable=False),
        sa.Column("source_color_id", sa.Integer(), nullable=False),
        sa.Column("ldraw_color_code", sa.Integer(), nullable=False),
        sa.UniqueConstraint(
            "source_system", "source_color_id", name="uq_external_color_map_source"
        ),
        sa.CheckConstraint(
            "source_system IN ('rebrickable', 'bricklink')",
            name="ck_external_color_map_source_system",
        ),
    )

    op.create_table(
        "external_id_map_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("populated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("part_mapping_count", sa.Integer(), nullable=False),
        sa.Column("color_mapping_count", sa.Integer(), nullable=False),
        sa.Column("ambiguous_part_count", sa.Integer(), nullable=False),
        sa.Column("fetcher_version", sa.String(length=32), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("external_id_map_state")
    op.drop_table("external_color_map")
    op.drop_index("ix_external_part_id_map_lookup", table_name="external_part_id_map")
    op.drop_table("external_part_id_map")
