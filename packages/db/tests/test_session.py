"""Session setup tests. None of these need a running database:
creating an engine or session does not connect until the first query."""

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from ms_db.session import LOCAL_DATABASE_URL, database_url, get_engine, new_session


@pytest.fixture(autouse=True)
def fresh_engine_cache() -> Iterator[None]:
    """get_engine() caches its engine; reset it so tests don't leak into each other."""
    get_engine.cache_clear()
    yield
    get_engine.cache_clear()


def test_local_url_points_at_the_docker_database() -> None:
    assert LOCAL_DATABASE_URL == (
        "postgresql+psycopg://marketsentry:marketsentry@localhost:5432/marketsentry"
    )


def test_database_url_defaults_to_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert database_url() == LOCAL_DATABASE_URL


def test_database_url_can_be_overridden(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db.example:5432/other")

    assert database_url() == "postgresql+psycopg://u:p@db.example:5432/other"


def test_engine_uses_the_configured_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db.example:5432/other")

    engine = get_engine()

    assert isinstance(engine, Engine)
    assert engine.url.host == "db.example"
    assert engine.url.database == "other"


def test_engine_is_created_once() -> None:
    # One engine (one connection pool) per process, not one per call.
    assert get_engine() is get_engine()


def test_new_session_is_bound_to_the_engine() -> None:
    with new_session() as session:
        assert isinstance(session, Session)
        assert session.get_bind() is get_engine()


def test_each_call_gives_a_new_session() -> None:
    with new_session() as first, new_session() as second:
        assert first is not second
