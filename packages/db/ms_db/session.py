import os
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

LOCAL_DATABASE_URL = "postgresql+psycopg://marketsentry:marketsentry@localhost:5432/marketsentry"


def database_url() -> str:
    return os.environ.get("DATABASE_URL", LOCAL_DATABASE_URL)


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_engine(database_url(), pool_pre_ping=True)


def new_session() -> Session:
    return Session(get_engine())
