from __future__ import annotations

from collections.abc import Callable, Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

SessionDependency = Callable[[], Iterator[Session]]


def sqlalchemy_database_url(database_url: str | None = None) -> str:
    url = database_url or get_settings().database_url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def build_engine(database_url: str | None = None) -> Engine:
    return create_engine(sqlalchemy_database_url(database_url), pool_pre_ping=True)


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Process-wide engine, created on first use — importing this module
    must not require DATABASE_URL to be set."""
    return build_engine()


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_session() -> Iterator[Session]:
    with get_session_factory()() as session:
        yield session
