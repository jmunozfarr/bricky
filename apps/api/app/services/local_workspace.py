from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Workspace


LOCAL_WORKSPACE_SLUG = "local-default"
LOCAL_WORKSPACE_NAME = "Local workspace"


def resolve_local_workspace(session: Session) -> Workspace:
    """Resolve the hidden single-user workspace with a concurrency-safe upsert."""

    session.execute(
        insert(Workspace)
        .values(slug=LOCAL_WORKSPACE_SLUG, name=LOCAL_WORKSPACE_NAME)
        .on_conflict_do_nothing(index_elements=[Workspace.slug])
    )
    workspace = session.scalar(
        select(Workspace).where(Workspace.slug == LOCAL_WORKSPACE_SLUG)
    )
    if workspace is None:
        raise RuntimeError("Unable to resolve the local workspace")
    return workspace
