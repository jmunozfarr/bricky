from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.database import build_engine, sqlalchemy_database_url
from app.models import Base, Workspace
from app.services.local_workspace import LOCAL_WORKSPACE_NAME, LOCAL_WORKSPACE_SLUG


@pytest.fixture
def catalog_session_factory() -> Iterator[sessionmaker[Session]]:
    schema = f"test_{uuid.uuid4().hex}"
    admin_engine = build_engine()
    with admin_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))

    test_engine = create_engine(
        sqlalchemy_database_url(),
        connect_args={"options": f"-csearch_path={schema}"},
    )
    Base.metadata.create_all(test_engine)
    factory = sessionmaker(bind=test_engine, expire_on_commit=False)
    # Mirrors the alembic data migration: the local workspace is seeded, not
    # lazily upserted by request handlers.
    with factory() as session:
        session.add(Workspace(slug=LOCAL_WORKSPACE_SLUG, name=LOCAL_WORKSPACE_NAME))
        session.commit()
    try:
        yield factory
    finally:
        test_engine.dispose()
        with admin_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()
