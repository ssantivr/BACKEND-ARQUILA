"""How many SQL statements the heavy project operations send, whatever the size of the project.

A project with more plans, rooms and components must not need more SELECT statements: what grows
with the project is the data each one returns, not their number.
"""

import pytest
from sqlalchemy import event

from tests.helpers import register

SQUARE = [{"x_m": 0, "y_m": 0}, {"x_m": 10, "y_m": 0}, {"x_m": 10, "y_m": 10}]
ROOMS_PER_PLAN = 4
COMPONENTS_PER_PLAN = 6


@pytest.fixture
def statements(engine):
    sent: list[str] = []

    def record(_connection, _cursor, statement, *_details):
        sent.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    yield sent
    event.remove(engine, "before_cursor_execute", record)


def selects(sent: list[str]) -> int:
    return sum(1 for statement in sent if statement.lstrip().upper().startswith("SELECT"))


def build_project(client, name: str, plans: int) -> int:
    project_id = client.post("/projects", json={"name": name}).json()["id"]

    for index in range(2):
        terrain = {"name": f"Lot {index}", "area_m2": 100, "points": SQUARE}
        assert client.post(f"/projects/{project_id}/terrains", json=terrain).status_code == 201

    for level in range(plans):
        plan = client.post(f"/projects/{project_id}/plans", json={"title": f"Plan {level}"})
        plan_id = plan.json()["id"]

        for index in range(ROOMS_PER_PLAN):
            room = {
                "plan_id": plan_id,
                "name": f"Room {level}-{index}",
                "category": "living",
                "x_m": index * 4,
                "y_m": 0,
                "width_m": 3,
                "depth_m": 3,
            }
            assert client.post(f"/projects/{project_id}/rooms", json=room).status_code == 201

        for index in range(COMPONENTS_PER_PLAN):
            component = {
                "plan_id": plan_id,
                "kind": "column",
                "name": f"Column {level}-{index}",
                "x_m": index,
                "y_m": 0,
                "width_m": 0.3,
                "depth_m": 0.3,
                "height_m": 3,
            }
            created = client.post(f"/projects/{project_id}/components", json=component)
            assert created.status_code == 201

    for index in range(3):
        material = {"name": f"Material {index}", "unit": "u", "quantity": 1, "unit_cost": 1}
        assert client.post(f"/projects/{project_id}/materials", json=material).status_code == 201

    return project_id


def measure(client, statements, method: str, url: str, **options) -> int:
    statements.clear()
    response = client.request(method, url, **options)
    assert response.status_code < 300, response.text

    return selects(statements)


@pytest.fixture
def small_and_large(client):
    register(client)

    return build_project(client, "Small", plans=1), build_project(client, "Large", plans=4)


# Measured once the eager loading is in place, on SQLite and on PostgreSQL; a margin of none, so
# that a new lazy load shows up here.
SAVE_VERSION_SELECTS = 23
DUPLICATE_SELECTS = 31


def test_saving_a_version_sends_the_same_selects_whatever_the_number_of_plans(
    client, statements, small_and_large
):
    small, large = small_and_large

    with_one = measure(client, statements, "POST", f"/projects/{small}/versions", json={})
    with_four = measure(client, statements, "POST", f"/projects/{large}/versions", json={})

    assert with_four == with_one
    assert with_four <= SAVE_VERSION_SELECTS


def test_duplicating_sends_the_same_selects_whatever_the_number_of_plans(
    client, statements, small_and_large
):
    small, large = small_and_large

    with_one = measure(client, statements, "POST", f"/projects/{small}/duplicate", json={})
    with_four = measure(client, statements, "POST", f"/projects/{large}/duplicate", json={})

    assert with_four == with_one
    assert with_four <= DUPLICATE_SELECTS


def test_the_snapshot_still_holds_every_plan_room_and_component(client, small_and_large):
    _, large = small_and_large

    version = client.post(f"/projects/{large}/versions", json={}).json()
    contents = client.get(f"/versions/{version['id']}").json()["snapshot"]

    assert len(contents["plans"]) == 4
    assert {len(plan["rooms"]) for plan in contents["plans"]} == {ROOMS_PER_PLAN}
    assert {len(plan["components"]) for plan in contents["plans"]} == {COMPONENTS_PER_PLAN}
    assert {len(terrain["points"]) for terrain in contents["terrains"]} == {len(SQUARE)}


PNG = b"\x89PNG\r\n\x1a\n" + b"fake image data"
# Every table that holds rows of a project, directly or through a parent of the project.
PROJECT_ROWS = {
    "terrains": "project_id = :id",
    "terrain_points": "terrain_id NOT IN (SELECT id FROM terrains)",
    "plans": "project_id = :id",
    "rooms": "project_id = :id",
    "structural_components": "project_id = :id",
    "files": "project_id = :id",
    "file_contents": "file_id NOT IN (SELECT id FROM files)",
    "materials": "project_id = :id",
    "tasks": "project_id = :id",
    "project_versions": "project_id = :id",
    "activity_log": "project_id = :id",
    "elevations": "project_id = :id",
    "scene_settings": "project_id = :id",
    "walkthrough_points": "project_id = :id",
}
DELETE_SELECTS = 9


def test_deleting_a_project_sends_the_same_selects_whatever_the_number_of_plans(
    client, statements, small_and_large
):
    small, large = small_and_large

    with_one = measure(client, statements, "DELETE", f"/projects/{small}")
    with_four = measure(client, statements, "DELETE", f"/projects/{large}")

    assert with_four == with_one
    assert with_four <= DELETE_SELECTS


def test_deleting_a_project_leaves_no_rows_and_never_reads_file_contents(
    client, statements, engine, small_and_large, monkeypatch
):
    from sqlalchemy import text

    monkeypatch.setenv("FILE_STORAGE", "database")
    _, large = small_and_large
    uploaded = client.post(
        f"/projects/{large}/files", files={"file": ("plan.png", PNG, "image/png")}
    )
    assert uploaded.status_code == 201
    assert client.post(f"/projects/{large}/versions", json={}).status_code == 201

    statements.clear()
    assert client.delete(f"/projects/{large}").status_code == 204

    assert not [sql for sql in statements if "file_contents" in sql and "SELECT" in sql.upper()]

    with engine.connect() as connection:
        left = {
            table: connection.scalar(
                text(f"SELECT count(*) FROM {table} WHERE {where}"), {"id": large}
            )
            for table, where in PROJECT_ROWS.items()
        }

    assert left == dict.fromkeys(PROJECT_ROWS, 0)
