"""The demo versions of seed.sql, compared with take() and opened through the API.

The seed is PostgreSQL SQL, so these tests run only with TEST_DATABASE_URL.
"""

import os
from datetime import datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.migrate import seed_file
from app.models import Project, ProjectVersion
from app.services.project_snapshot import take
from app.services.undo_history import encode_value

pytestmark = pytest.mark.skipif(
    os.environ.get("TEST_DATABASE_URL") is None,
    reason="seed.sql is PostgreSQL SQL: set TEST_DATABASE_URL",
)

# Public demo account of seed.sql (BASE-DE-DATOS-ARQUILA/README.md).
DEMO = {"email": "demo@example.com", "password": "arquila-demo"}
# What the first version of Casa Los Arrayanes leaves out: it is the design before the work.
BEFORE_INTERIOR_WORK = ("project", "materials", "tasks")


@pytest.fixture
def seeded(engine):
    with engine.begin() as connection:
        connection.exec_driver_sql(seed_file().read_text(encoding="utf-8"))

    return engine


def seeded_versions(engine):
    """Each version of the seed, with what take() gives for its project today."""
    with Session(engine) as session:
        versions = session.scalars(select(ProjectVersion).order_by(ProjectVersion.id)).all()

        return {
            (session.get(Project, version.project_id).name, version.version_number): (
                version.snapshot,
                take(session.get(Project, version.project_id)),
            )
            for version in versions
        }


def keys_by_path(document):
    """The keys found at each place of the document, such as snapshot.plans[].rooms[]."""
    found = {}

    def walk(value, path):
        if isinstance(value, dict):
            found.setdefault(path, set()).update(value)

            for key, child in value.items():
                walk(child, f"{path}.{key}")
        elif isinstance(value, list):
            for item in value:
                walk(item, f"{path}[]")

    walk(document, "snapshot")
    return found


def test_the_seed_versions_are_documents_that_take_writes(seeded):
    versions = seeded_versions(seeded)

    assert set(versions) == {
        ("Casa Los Arrayanes", 1),
        ("Casa Los Arrayanes", 2),
        ("Edificio Mirador", 1),
    }

    for name, (stored, live) in versions.items():
        stored_keys, live_keys = keys_by_path(stored), keys_by_path(live)

        for path, keys in stored_keys.items():
            assert keys == live_keys[path], (name, path)

    assert versions["Casa Los Arrayanes", 2][0] == versions["Casa Los Arrayanes", 2][1]
    assert versions["Edificio Mirador", 1][0] == versions["Edificio Mirador", 1][1]

    first, current = versions["Casa Los Arrayanes", 1]
    assert {key: value for key, value in first.items() if key not in BEFORE_INTERIOR_WORK} == {
        key: value for key, value in current.items() if key not in BEFORE_INTERIOR_WORK
    }


@pytest.mark.parametrize(
    "moment",
    [
        datetime(2026, 10, 23, 20, 16, 5, 931150),
        datetime(2026, 10, 23, 20, 16, 5, 900000),
        datetime(2026, 10, 23, 20, 16, 5),
        datetime(2026, 10, 23, 20, 16, 5, 1),
    ],
    ids=["trailing-zero", "one-digit", "whole-second", "one-microsecond"],
)
def test_the_seed_writes_timestamps_the_way_take_does(engine, moment):
    # Every row of the seed gets the time of its transaction, so a time whose microseconds end
    # in zero would only show up now and then; here the times are chosen. The functions of the
    # seed are temporary, so they are called on the connection that loaded it.
    with engine.begin() as connection:
        connection.exec_driver_sql(seed_file().read_text(encoding="utf-8"))
        written = connection.execute(
            text(
                "SELECT pg_temp.snapshot_values('materials', "
                "jsonb_build_object('created_at', CAST(:moment AS timestamp)), '{created_at}')"
            ),
            {"moment": moment},
        ).scalar_one()

    assert written == {"created_at": encode_value(moment)}


def test_the_first_version_of_the_house_is_not_the_second(seeded):
    versions = seeded_versions(seeded)
    first = versions["Casa Los Arrayanes", 1][0]
    second = versions["Casa Los Arrayanes", 2][0]

    assert first != second
    assert first["tasks"] == []
    assert second["tasks"] != []
    assert first["project"]["progress"] == 0
    assert len(first["materials"]) < len(second["materials"])


def test_the_seed_versions_open_and_restore_through_the_api(client, seeded):
    assert client.post("/auth/login", json=DEMO).status_code == 200

    for path in ("/projects/1/versions", "/projects/2/versions", "/versions/1"):
        response = client.get(path)
        assert response.status_code == 200, (path, response.text)

    for version in client.get("/projects/1/versions").json():
        assert version["contents"]["plans"] > 0

    response = client.post("/versions/1/restore")
    assert response.status_code == 200, response.text
