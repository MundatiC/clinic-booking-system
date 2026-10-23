"""Test infrastructure: a real Postgres database built by the Alembic migrations.

- Session scope: drop/recreate the test database and run `alembic upgrade head`
  (so every test run also exercises the migrations).
- Function scope: TRUNCATE all tables and re-seed. Truncation, rather than
  rolling back a wrapping transaction, is deliberate: the concurrency tests use
  several real connections from several threads, which must see committed data.
"""

import os

from sqlalchemy.engine import make_url

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://clinic:clinic@localhost:55432/clinic_test"
)
# Must happen before the app reads its (cached) settings.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["ENVIRONMENT"] = "test"
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import Engine, create_engine, text  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db.session import get_engine, get_sessionmaker  # noqa: E402
from scripts.seed import seed  # noqa: E402


def _recreate_database(url: str) -> None:
    target = make_url(url)
    admin = create_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{target.database}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{target.database}"'))
    admin.dispose()


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    _recreate_database(TEST_DATABASE_URL)
    cfg = Config("alembic.ini")
    cfg.attributes["url"] = TEST_DATABASE_URL
    command.upgrade(cfg, "head")
    eng = get_engine()
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> Iterator[sessionmaker[Session]]:
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    factory = get_sessionmaker()
    with factory() as s:
        seed(s)
    yield factory


@pytest.fixture
def db(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    with session_factory() as s:
        yield s


# ---- API fixtures -------------------------------------------------------------------

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.clock import FixedClock  # noqa: E402
from app.main import create_app  # noqa: E402
from tests.utils import NOW  # noqa: E402


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(NOW)


@pytest.fixture
def app(session_factory: sessionmaker[Session], clock: FixedClock) -> FastAPI:
    return create_app(clock=clock)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c
