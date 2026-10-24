import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, event, make_url
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base, get_session
from app.main import app
from app.migrate import apply_migrations
from app.services.login_limiter import (
    ip_login_limiter,
    login_limiter,
    password_change_limiter,
    register_ip_limiter,
    reset_request_limiter,
)
from app.services.undo_history import undo_history
from tests.helpers import seed_access_catalog

CATALOG_TABLES = {"roles", "permissions", "role_permissions"}


def create_test_engine() -> Engine:
    url = os.environ.get("TEST_DATABASE_URL")

    if url is None:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        # SQLite ignores foreign keys unless asked, so without this the suite would never see
        # a reference to another project's row, nor a cascade, that PostgreSQL enforces.
        event.listen(
            engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON")
        )
        Base.metadata.create_all(engine)
        seed_access_catalog(engine)
        return engine

    if not (make_url(url).database or "").endswith("test"):
        raise RuntimeError(
            "TEST_DATABASE_URL must point to a database whose name ends in 'test': "
            "every table in it is emptied before each test"
        )

    engine = create_engine(url)
    tables = ", ".join(
        table.name for table in Base.metadata.sorted_tables if table.name not in CATALOG_TABLES
    )

    apply_migrations(engine)

    with engine.begin() as connection:
        connection.exec_driver_sql(f"TRUNCATE {tables} RESTART IDENTITY CASCADE")

    return engine


@pytest.fixture
def engine():
    engine = create_test_engine()

    yield engine

    engine.dispose()


@pytest.fixture
def client(tmp_path, monkeypatch, engine):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:9")

    def override_get_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session

    yield TestClient(app)

    app.dependency_overrides.clear()
    undo_history.clear()
    login_limiter.clear()
    ip_login_limiter.clear()
    reset_request_limiter.clear()
    password_change_limiter.clear()
    register_ip_limiter.clear()
