"""Seed the hidden local-default workspace.

The workspace was previously created lazily by a concurrency-safe upsert on
every request that resolved it, which forced GET handlers to commit. Seeding
it here makes resolution a plain SELECT.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260706_04"
down_revision: str | None = "20260629_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LOCAL_WORKSPACE_SLUG = "local-default"
LOCAL_WORKSPACE_NAME = "Local workspace"


def upgrade() -> None:
    op.execute(
        sa.text(
            "INSERT INTO workspaces (slug, name) "
            "VALUES (:slug, :name) ON CONFLICT (slug) DO NOTHING"
        ).bindparams(slug=LOCAL_WORKSPACE_SLUG, name=LOCAL_WORKSPACE_NAME)
    )


def downgrade() -> None:
    # The workspace owns personal data; removing it on downgrade would
    # cascade into inventory and imported models. Keep it.
    pass
