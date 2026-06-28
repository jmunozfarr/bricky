"""Create imported model, BOM, and structured issue tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260629_03"
down_revision: str | None = "20260628_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "imported_models",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("safe_filename", sa.String(length=255), nullable=False),
        sa.Column("source_format", sa.String(length=8), nullable=False),
        sa.Column("relative_storage_path", sa.String(length=512), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("import_status", sa.String(length=32), nullable=False),
        sa.Column("declared_step_count", sa.Integer(), nullable=False),
        sa.Column("total_part_quantity", sa.Integer(), nullable=False),
        sa.Column("unique_part_color_count", sa.Integer(), nullable=False),
        sa.Column("unresolved_reference_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "workspace_id", "source_sha256", name="uq_models_workspace_source_sha256"
        ),
    )
    op.create_index("ix_imported_models_public_id", "imported_models", ["public_id"], unique=True)
    op.create_index("ix_imported_models_workspace_id", "imported_models", ["workspace_id"])
    op.create_index("ix_imported_models_import_status", "imported_models", ["import_status"])
    op.create_index(
        "ix_models_workspace_created", "imported_models", ["workspace_id", "created_at"]
    )

    op.create_table(
        "model_bom_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "model_id",
            sa.Integer(),
            sa.ForeignKey("imported_models.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("part_id", sa.String(length=64), nullable=False),
        sa.Column("color_code", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_model_bom_quantity_positive"),
        sa.UniqueConstraint(
            "model_id", "part_id", "color_code", name="uq_model_bom_part_color"
        ),
    )
    op.create_index("ix_model_bom_items_model_id", "model_bom_items", ["model_id"])
    op.create_index("ix_model_bom_items_part_id", "model_bom_items", ["part_id"])
    op.create_index("ix_model_bom_items_color_code", "model_bom_items", ["color_code"])
    op.create_index("ix_model_bom_model_part", "model_bom_items", ["model_id", "part_id"])
    op.create_index("ix_model_bom_model_color", "model_bom_items", ["model_id", "color_code"])

    op.create_table(
        "model_import_issues",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "model_id",
            sa.Integer(),
            sa.ForeignKey("imported_models.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("message", sa.String(length=512), nullable=False),
        sa.Column("referenced_filename", sa.String(length=255), nullable=True),
    )
    op.create_index("ix_model_import_issues_model_id", "model_import_issues", ["model_id"])
    op.create_index(
        "ix_model_issues_model_severity",
        "model_import_issues",
        ["model_id", "severity"],
    )


def downgrade() -> None:
    op.drop_table("model_import_issues")
    op.drop_table("model_bom_items")
    op.drop_table("imported_models")
