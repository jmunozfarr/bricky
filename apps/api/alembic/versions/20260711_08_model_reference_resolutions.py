"""Create model_reference_resolutions.

Personal per-model decisions (map to an official part, or ignore) about
source references the parser cannot resolve on its own. Keyed by natural
LDraw identifiers, never by rebuildable catalog rows.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260711_08"
down_revision: str | None = "20260711_07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_reference_resolutions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "model_id",
            sa.Integer(),
            sa.ForeignKey("imported_models.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_reference", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("target_part_id", sa.String(length=64), nullable=True),
        sa.Column("color_code", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("model_id", "source_reference", name="uq_model_resolution_source"),
        sa.CheckConstraint("action IN ('map', 'ignore')", name="ck_model_resolution_action"),
        sa.CheckConstraint(
            "action != 'map' OR target_part_id IS NOT NULL",
            name="ck_model_resolution_map_target",
        ),
    )
    op.create_index(
        "ix_model_reference_resolutions_model_id",
        "model_reference_resolutions",
        ["model_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_model_reference_resolutions_model_id", table_name="model_reference_resolutions"
    )
    op.drop_table("model_reference_resolutions")
