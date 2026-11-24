import pytest

from tests.helpers import register


@pytest.fixture
def user(client):
    return register(client)


def create_project(client, name="Demo House", **extra):
    return client.post("/projects", json={"name": name, **extra})


def test_create_project_belongs_to_the_logged_in_user(client, user):
    response = create_project(client, location="Quito")

    assert response.status_code == 201
    project = response.json()
    assert project["owner_id"] == user["id"]
    assert project["name"] == "Demo House"
    assert project["status"] == "draft"
    assert project["location"] == "Quito"
    assert client.get(f"/projects/{project['id']}").json() == project


def test_owner_id_in_the_request_is_ignored(client, user):
    response = client.post("/projects", json={"name": "Demo House", "owner_id": 999})

    assert response.status_code == 201
    assert response.json()["owner_id"] == user["id"]


def test_duplicate_name_for_same_owner_is_rejected(client, user):
    create_project(client)

    assert create_project(client).status_code == 409


def test_invalid_status_is_rejected(client, user):
    assert create_project(client, status="finished").status_code == 422


def test_list_filters_by_search_and_status(client, user):
    create_project(client, name="Lake House", status="active")
    create_project(client, name="City Tower")

    def names(**params):
        return [p["name"] for p in client.get("/projects", params=params).json()]

    assert names() == ["Lake House", "City Tower"]
    assert names(search="house") == ["Lake House"]
    assert names(status="draft") == ["City Tower"]
    assert names(search="%") == []


def test_update_project(client, user):
    project_id = create_project(client).json()["id"]
    create_project(client, name="City Tower")

    response = client.patch(f"/projects/{project_id}", json={"status": "active"})

    assert response.status_code == 200
    assert response.json()["status"] == "active"
    assert response.json()["name"] == "Demo House"

    conflict = client.patch(f"/projects/{project_id}", json={"name": "City Tower"})
    assert conflict.status_code == 409


def test_delete_project(client, user):
    project_id = create_project(client).json()["id"]

    assert client.delete(f"/projects/{project_id}").status_code == 204
    assert client.get(f"/projects/{project_id}").status_code == 404
    assert client.delete(f"/projects/{project_id}").status_code == 404


def test_description_over_the_length_limit_is_rejected(client, user):
    assert create_project(client, description="x" * 200).status_code == 201

    project_id = create_project(client, name="Second House").json()["id"]

    assert create_project(client, name="Third House", description="x" * 201).status_code == 422
    assert (
        client.patch(f"/projects/{project_id}", json={"description": "x" * 201}).status_code == 422
    )


def test_creating_the_same_name_at_once_is_a_conflict(client, monkeypatch):
    register(client)
    client.post("/projects", json={"name": "Demo House"})
    monkeypatch.setattr(
        "app.repositories.project_repository.ProjectRepository.get_by_owner_and_name",
        lambda self, owner_id, name: None,
    )

    response = client.post("/projects", json={"name": "Demo House"})

    assert response.status_code == 409
