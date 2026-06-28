"""Create official LDraw catalog tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260628_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "parts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("part_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("relative_path", sa.String(length=512), nullable=False),
        sa.Column("author", sa.String(length=256), nullable=True),
        sa.Column("category", sa.String(length=128), nullable=False),
        sa.Column("org_classification", sa.String(length=256), nullable=True),
        sa.Column("license", sa.String(length=512), nullable=True),
        sa.Column("keywords", sa.Text(), nullable=True),
        sa.Column("is_subpart", sa.Boolean(), nullable=False),
        sa.Column("is_shortcut", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("relative_path", name="uq_parts_relative_path"),
    )
    op.create_index("ix_parts_part_id", "parts", ["part_id"], unique=True)
    op.create_index("ix_parts_name", "parts", ["name"])
    op.create_index("ix_parts_category", "parts", ["category"])
    op.create_index(
        "ix_parts_category_visible", "parts", ["category", "is_subpart"]
    )
    op.create_index("ix_parts_is_subpart", "parts", ["is_subpart"])

    op.create_table(
        "ldraw_colors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("value_hex", sa.String(length=7), nullable=False),
        sa.Column("edge_hex", sa.String(length=7), nullable=True),
        sa.Column("alpha", sa.Integer(), nullable=False),
        sa.Column("luminance", sa.Integer(), nullable=True),
        sa.Column("finish", sa.String(length=64), nullable=True),
    )
    op.create_index("ix_ldraw_colors_code", "ldraw_colors", ["code"], unique=True)

    op.create_table(
        "catalog_index_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("library_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("part_count", sa.Integer(), nullable=False),
        sa.Column("color_count", sa.Integer(), nullable=False),
        sa.Column("indexer_version", sa.String(length=32), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_catalog_index_state_singleton"),
    )


def downgrade() -> None:
    op.drop_table("catalog_index_state")
    op.drop_index("ix_ldraw_colors_code", table_name="ldraw_colors")
    op.drop_table("ldraw_colors")
    op.drop_index("ix_parts_is_subpart", table_name="parts")
    op.drop_index("ix_parts_category_visible", table_name="parts")
    op.drop_index("ix_parts_category", table_name="parts")
    op.drop_index("ix_parts_name", table_name="parts")
    op.drop_index("ix_parts_part_id", table_name="parts")
    op.drop_table("parts")
