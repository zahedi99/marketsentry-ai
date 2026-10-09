"""Fixtures for tests that need a real Postgres.

Tests run against a separate database (`marketsentry_test` by default, or
$TEST_DATABASE_URL), created and migrated once per test run. Each test runs inside a
transaction that is rolled back afterwards, so tests never see each other's data.
If Postgres isn't reachable, these tests are skipped (start it with `make db-up`).
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"
DEFAULT_TEST_URL = "postgresql+psycopg://marketsentry:marketsentry@localhost:5432/marketsentry_test"


def test_database_url() -> str:
    return os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_URL)


test_database_url.__test__ = False  # type: ignore[attr-defined]  # not a test itself


def alembic_config(url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def _ensure_database_exists(url: str) -> None:
    """Create the test database if it's missing (connecting via the default `postgres` db)."""
    target = create_engine(url)
    admin = create_engine(
        target.url.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
        connect_args={"connect_timeout": 5},  # fail fast if Postgres is down
    )
    try:
        with admin.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": target.url.database},
            ).first()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{target.url.database}"'))
    finally:
        admin.dispose()
        target.dispose()


@pytest.fixture(scope="session")
def migrated_engine() -> Iterator[Engine]:
    url = test_database_url()
    try:
        _ensure_database_exists(url)
    except OperationalError:
        if os.environ.get("CI"):
            raise  # in CI a missing database is a real failure, not something to skip
        pytest.skip("Postgres is not reachable: start it with `make db-up`")
    command.upgrade(alembic_config(url), "head")
    engine = create_engine(url)
    yield engine
    engine.dispose()


@pytest.fixture
def session(migrated_engine: Engine) -> Iterator[Session]:
    """A session whose work is rolled back after the test, even if the code commits."""
    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        db_session = Session(bind=connection, join_transaction_mode="create_savepoint")
        try:
            yield db_session
        finally:
            db_session.close()
            transaction.rollback()
