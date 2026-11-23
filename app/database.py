import os
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import URL, Engine, create_engine, make_url
from sqlalchemy.orm import DeclarativeBase, Session


class Base(DeclarativeBase):
    pass


PLAIN_POSTGRES_DRIVERS = ("postgres", "postgresql")


def database_url(value: str) -> URL:
    url = make_url(value)

    if url.drivername in PLAIN_POSTGRES_DRIVERS:
        return url.set(drivername="postgresql+psycopg")

    return url


@lru_cache
def get_engine() -> Engine:
    configured = os.environ.get("DATABASE_URL")

    if not configured:
        raise RuntimeError("DATABASE_URL environment variable is not set")

    # hide_parameters: the values of a failed query would end up in the log.
    return create_engine(database_url(configured), pool_pre_ping=True, hide_parameters=True)


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session
