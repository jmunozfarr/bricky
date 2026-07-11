"""Create the rebuildable ldraw_primitives lookup table.

LDraw sources may reference primitives bare (`axlehol8.dat`), resolving
through the library's p/ directory; the model parser needs the indexed
names to treat them as rendering-only geometry instead of unresolved parts.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260711_06"
down_revision: str | None = "20260706_05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ldraw_primitives",
        sa.Column("name", sa.String(length=255), primary_key=True),
    )


def downgrade() -> None:
    op.drop_table("ldraw_primitives")
