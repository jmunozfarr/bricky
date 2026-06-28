"""Create the deterministic local workspace and personal inventory."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260628_02"
down_revision: str | None = "20260628_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
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
    )
    op.create_index("ix_workspaces_slug", "workspaces", ["slug"], unique=True)
    op.execute(
        "INSERT INTO workspaces (slug, name) VALUES "
        "('local-default', 'Local workspace') ON CONFLICT (slug) DO NOTHING"
    )

    op.create_table(
        "inventory_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("part_id", sa.String(length=64), nullable=False),
        sa.Column("color_code", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
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
        sa.CheckConstraint("quantity > 0", name="ck_inventory_quantity_positive"),
        sa.UniqueConstraint(
            "workspace_id",
            "part_id",
            "color_code",
            name="uq_inventory_workspace_part_color",
        ),
    )
    op.create_index("ix_inventory_items_workspace_id", "inventory_items", ["workspace_id"])
    op.create_index("ix_inventory_items_part_id", "inventory_items", ["part_id"])
    op.create_index("ix_inventory_items_color_code", "inventory_items", ["color_code"])
    op.create_index(
        "ix_inventory_workspace_part",
        "inventory_items",
        ["workspace_id", "part_id"],
    )
    op.create_index(
        "ix_inventory_workspace_color",
        "inventory_items",
        ["workspace_id", "color_code"],
    )


def downgrade() -> None:
    op.drop_table("inventory_items")
    op.drop_index("ix_workspaces_slug", table_name="workspaces")
    op.drop_table("workspaces")
