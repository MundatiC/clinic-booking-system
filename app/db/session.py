"""Engine and session factory."""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings


def build_engine(settings: Settings) -> Engine:
    return create_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_seconds,
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args={
            "connect_timeout": 5,
            # Server-side guard: no single statement may hang a worker.
            "options": f"-c statement_timeout={settings.db_statement_timeout_ms}"
            " -c lock_timeout=3000",
        },
    )


@lru_cache
def get_engine() -> Engine:
    return build_engine(get_settings())


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request, closed afterwards."""
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()
