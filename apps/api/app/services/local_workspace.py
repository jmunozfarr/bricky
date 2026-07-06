from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Workspace

LOCAL_WORKSPACE_SLUG = "local-default"
LOCAL_WORKSPACE_NAME = "Local workspace"


def resolve_local_workspace(session: Session) -> Workspace:
    """Resolve the hidden single-user workspace.

    The workspace is seeded by an Alembic data migration (and by the test
    fixtures), so resolution is a plain read — request handlers no longer
    upsert or commit to obtain it.
    """

    workspace = session.scalar(select(Workspace).where(Workspace.slug == LOCAL_WORKSPACE_SLUG))
    if workspace is None:
        raise RuntimeError("The local workspace is missing; run `alembic upgrade head` to seed it")
    return workspace
