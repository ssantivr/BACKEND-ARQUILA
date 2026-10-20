import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import register


@pytest.fixture
def user(client):
    return register(client)


@pytest.fixture
def project_id(client, user):
    return client.post("/projects", json={"name": "Demo House"}).json()["id"]


@pytest.fixture
def stranger(client, project_id):
    other = TestClient(app)
    register(other, name="Eve", email="eve@example.com")
    return other


def create_task(client, project_id, **values):
    return client.post(f"/projects/{project_id}/tasks", json={"title": "Pedir permisos", **values})


def test_create_list_and_read_a_task(client, project_id, user):
    response = create_task(
        client, project_id, description="Municipio", due_date="2026-11-30", assignee_id=user["id"]
    )

    assert response.status_code == 201
    task = response.json()
    assert task["project_id"] == project_id
    assert task["status"] == "todo"
    assert task["progress"] == 0
    assert task["due_date"] == "2026-11-30"
    assert task["assignee_id"] == user["id"]
    assert task["created_by"] == user["id"]

    assert client.get(f"/tasks/{task['id']}").json() == task
    assert client.get(f"/projects/{project_id}/tasks").json() == [task]


def test_list_filters_by_status(client, project_id):
    create_task(client, project_id, title="A")
    create_task(client, project_id, title="B", status="in_progress", progress=50)

    listed = client.get(f"/projects/{project_id}/tasks", params={"status": "in_progress"}).json()

    assert [task["title"] for task in listed] == ["B"]


def test_a_task_that_is_done_is_complete(client, project_id):
    done = create_task(client, project_id, status="done").json()
    assert done["progress"] == 100

    task = create_task(client, project_id, title="Otra", progress=40).json()
    finished = client.patch(f"/tasks/{task['id']}", json={"status": "done"}).json()
    assert finished["progress"] == 100

    reopened = client.patch(f"/tasks/{task['id']}", json={"status": "in_progress", "progress": 70})
    assert reopened.json()["progress"] == 70


def test_done_with_less_progress_is_rejected(client, project_id):
    response = create_task(client, project_id, status="done", progress=50)

    assert response.status_code == 422
    assert response.json() == {"detail": "A task that is done must have a progress of 100"}

    task = create_task(client, project_id, status="done").json()
    assert client.patch(f"/tasks/{task['id']}", json={"progress": 20}).status_code == 422


def test_update_and_clear_optional_fields(client, project_id, user):
    task = create_task(client, project_id, description="x", due_date="2026-11-30").json()

    updated = client.patch(
        f"/tasks/{task['id']}", json={"title": "Permisos", "description": None, "due_date": None}
    ).json()

    assert updated["title"] == "Permisos"
    assert updated["description"] is None
    assert updated["due_date"] is None

    unchanged = client.patch(f"/tasks/{task['id']}", json={"title": None}).json()
    assert unchanged["title"] == "Permisos"


def test_delete_a_task(client, project_id):
    task = create_task(client, project_id).json()

    assert client.delete(f"/tasks/{task['id']}").status_code == 204
    assert client.get(f"/tasks/{task['id']}").status_code == 404
    assert client.delete(f"/tasks/{task['id']}").status_code == 404


def test_tasks_are_recorded_in_the_activity(client, project_id):
    task = create_task(client, project_id).json()
    client.patch(f"/tasks/{task['id']}", json={"progress": 10})
    client.delete(f"/tasks/{task['id']}")

    items = client.get(f"/projects/{project_id}/activity", params={"entity_type": "task"}).json()

    assert [item["action"] for item in items["items"]] == ["deleted", "updated", "created"]


@pytest.mark.parametrize(
    "values",
    [
        {"title": ""},
        {"title": "x" * 161},
        {"status": "blocked"},
        {"progress": 101},
        {"progress": -5},
        {"due_date": "tomorrow"},
        {"description": "x" * 2001},
    ],
)
def test_invalid_data_is_rejected(client, project_id, values):
    assert create_task(client, project_id, **values).status_code == 422


def test_only_the_owner_can_be_assigned(client, project_id, stranger):
    other_id = stranger.get("/auth/me").json()["id"]

    response = create_task(client, project_id, assignee_id=other_id)

    assert response.status_code == 422
    assert response.json() == {"detail": "A task can only be assigned to the owner of the project"}


def test_tasks_need_a_session(client, project_id):
    task = create_task(client, project_id).json()
    anonymous = TestClient(app)

    assert anonymous.get(f"/projects/{project_id}/tasks").status_code == 401
    assert create_task(anonymous, project_id).status_code == 401
    assert anonymous.get(f"/tasks/{task['id']}").status_code == 401
    assert anonymous.patch(f"/tasks/{task['id']}", json={"title": "x"}).status_code == 401
    assert anonymous.delete(f"/tasks/{task['id']}").status_code == 401


def test_tasks_of_other_users_are_not_found(client, project_id, stranger):
    task = create_task(client, project_id).json()

    assert stranger.get(f"/projects/{project_id}/tasks").status_code == 404
    assert create_task(stranger, project_id).status_code == 404
    assert stranger.get(f"/tasks/{task['id']}").json() == {"detail": "Task not found"}
    assert stranger.patch(f"/tasks/{task['id']}", json={"title": "x"}).status_code == 404
    assert stranger.delete(f"/tasks/{task['id']}").status_code == 404
    assert client.get(f"/tasks/{task['id']}").status_code == 200


def test_tasks_are_kept_in_versions_and_copies(client, project_id):
    create_task(client, project_id, title="Planos", due_date="2026-12-01", progress=30)
    version = client.post(f"/projects/{project_id}/versions").json()
    assert version["contents"]["tasks"] == 1

    for task in client.get(f"/projects/{project_id}/tasks").json():
        client.delete(f"/tasks/{task['id']}")
    client.post(f"/versions/{version['id']}/restore")

    restored = client.get(f"/projects/{project_id}/tasks").json()
    assert [(t["title"], t["due_date"], t["progress"]) for t in restored] == [
        ("Planos", "2026-12-01", 30)
    ]

    copy = client.post(f"/projects/{project_id}/duplicate").json()
    assert [t["title"] for t in client.get(f"/projects/{copy['id']}/tasks").json()] == ["Planos"]
