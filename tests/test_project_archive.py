import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import register

PNG = b"\x89PNG\r\n\x1a\n" + b"fake image data"
PDF = b"%PDF-1.7\nfake document"


@pytest.fixture
def project_id(client):
    register(client)
    return client.post("/projects", json={"name": "Demo House", "status": "active"}).json()["id"]


@pytest.fixture
def stranger(client, project_id):
    other = TestClient(app)
    register(other, name="Eve", email="eve@example.com")
    return other


def upload(client, project_id, content=PNG, name="cover.png"):
    return client.post(
        f"/projects/{project_id}/files", files={"file": (name, content, "image/png")}
    ).json()


def test_new_fields_are_in_the_project(client, project_id):
    project = client.get(f"/projects/{project_id}").json()

    assert project["progress"] == 0
    assert project["archived_at"] is None
    assert project["cover_file_id"] is None


def test_archive_and_unarchive_keep_the_previous_status(client, project_id):
    archived = client.post(f"/projects/{project_id}/archive")

    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"
    assert archived.json()["archived_at"] is not None

    again = client.post(f"/projects/{project_id}/archive")
    assert again.json()["archived_at"] == archived.json()["archived_at"]

    restored = client.post(f"/projects/{project_id}/unarchive")

    assert restored.status_code == 200
    assert restored.json()["status"] == "active"
    assert restored.json()["archived_at"] is None


def test_unarchive_without_a_known_status_makes_the_project_active(client, project_id):
    client.patch(f"/projects/{project_id}", json={"status": "archived"})

    assert client.get(f"/projects/{project_id}").json()["archived_at"] is not None

    restored = client.post(f"/projects/{project_id}/unarchive").json()

    assert restored["status"] == "active"
    assert restored["archived_at"] is None


def test_unarchiving_a_project_that_is_not_archived_changes_nothing(client, project_id):
    response = client.post(f"/projects/{project_id}/unarchive")

    assert response.status_code == 200
    assert response.json()["status"] == "active"


def test_changing_the_status_away_from_archived_clears_the_date(client, project_id):
    client.post(f"/projects/{project_id}/archive")

    project = client.patch(f"/projects/{project_id}", json={"status": "draft"}).json()

    assert project["archived_at"] is None


def test_archive_needs_a_session_and_an_own_project(client, project_id, stranger):
    assert stranger.post(f"/projects/{project_id}/archive").status_code == 404
    assert stranger.post(f"/projects/{project_id}/unarchive").status_code == 404
    assert TestClient(app).post(f"/projects/{project_id}/archive").status_code == 401
    assert client.post("/projects/9999/archive").status_code == 404


def test_progress_is_editable_and_bounded(client, project_id):
    assert client.patch(f"/projects/{project_id}", json={"progress": 55}).json()["progress"] == 55
    assert client.patch(f"/projects/{project_id}", json={"progress": 101}).status_code == 422
    assert client.patch(f"/projects/{project_id}", json={"progress": -1}).status_code == 422


def test_cover_is_an_image_of_the_project(client, project_id):
    image = upload(client, project_id)

    response = client.patch(f"/projects/{project_id}", json={"cover_file_id": image["id"]})

    assert response.status_code == 200
    assert response.json()["cover_file_id"] == image["id"]

    cleared = client.patch(f"/projects/{project_id}", json={"cover_file_id": None})
    assert cleared.json()["cover_file_id"] is None


def test_a_pdf_cannot_be_the_cover(client, project_id):
    document = upload(client, project_id, content=PDF, name="plan.pdf")

    response = client.patch(f"/projects/{project_id}", json={"cover_file_id": document["id"]})

    assert response.status_code == 422
    assert response.json() == {"detail": "The cover must be a PNG, JPEG or WebP image"}


def test_the_cover_must_belong_to_the_same_project(client, project_id, stranger):
    other_project = client.post("/projects", json={"name": "Other"}).json()["id"]
    image = upload(client, other_project)

    response = client.patch(f"/projects/{project_id}", json={"cover_file_id": image["id"]})
    assert response.status_code == 404

    foreign_project = stranger.post("/projects", json={"name": "Foreign"}).json()["id"]
    foreign_image = upload(stranger, foreign_project)

    response = client.patch(f"/projects/{project_id}", json={"cover_file_id": foreign_image["id"]})
    assert response.status_code == 404


def test_deleting_the_cover_file_clears_it(client, project_id):
    image = upload(client, project_id)
    client.patch(f"/projects/{project_id}", json={"cover_file_id": image["id"]})

    assert client.delete(f"/files/{image['id']}").status_code == 204
    assert client.get(f"/projects/{project_id}").json()["cover_file_id"] is None
