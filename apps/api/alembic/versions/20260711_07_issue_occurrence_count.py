"""Add occurrence_count to model_import_issues.

Issue rows are deduplicated per (code, message, referenced filename); the
count preserves how many physical reference occurrences each row stands for.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260711_07"
down_revision: str | None = "20260711_06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model_import_issues",
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("model_import_issues", "occurrence_count")
