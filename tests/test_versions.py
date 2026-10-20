import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import register

PNG = b"\x89PNG\r\n\x1a\n" + b"fake image data"
POLYGON = [{"x_m": 0, "y_m": 0}, {"x_m": 10, "y_m": 0}, {"x_m": 10, "y_m": 20}]


@pytest.fixture
def project_id(client):
    register(client)
    return client.post("/projects", json={"name": "Demo House", "location": "Quito"}).json()["id"]


@pytest.fixture
def stranger(client, project_id):
    other = TestClient(app)
    register(other, name="Eve", email="eve@example.com")
    return other


def fill(client, project_id):
    file = client.post(
        f"/projects/{project_id}/files", files={"file": ("plan.png", PNG, "image/png")}
    ).json()
    client.post(
        f"/projects/{project_id}/terrains",
        json={"name": "Lote", "area_m2": 200, "points": POLYGON},
    )
    client.post(
        f"/projects/{project_id}/materials",
        json={"name": "Cemento", "unit": "saco", "quantity": 12.5, "unit_cost": 8.75},
    )
    plan = client.post(
        f"/projects/{project_id}/plans", json={"title": "Planta baja", "file_id": file["id"]}
    ).json()
    room = {"plan_id": plan["id"], "name": "Sala", "x_m": 0, "y_m": 0, "width_m": 4, "depth_m": 5}
    client.post(f"/projects/{project_id}/rooms", json=room)
    client.post(
        f"/projects/{project_id}/components",
        json={
            **room,
            "name": "C1",
            "kind": "column",
            "width_m": 0.3,
            "depth_m": 0.3,
            "height_m": 3,
        },
    )
    client.post(
        f"/projects/{project_id}/elevations", json={"title": "Norte", "orientation": "north"}
    )
    client.patch(f"/projects/{project_id}", json={"progress": 30, "cover_file_id": file["id"]})
    return file


def contents(client, project_id):
    return {
        "terrains": [
            (t["name"], t["area_m2"], [(p["x_m"], p["y_m"]) for p in t["points"]])
            for t in client.get(f"/projects/{project_id}/terrains").json()
        ],
        "materials": [
            (m["name"], m["quantity"], m["unit_cost"])
            for m in client.get(f"/projects/{project_id}/materials").json()
        ],
        "plans": [
            (p["title"], p["file_id"] is not None)
            for p in client.get(f"/projects/{project_id}/plans").json()
        ],
        "rooms": [
            (r["name"], r["width_m"]) for r in client.get(f"/projects/{project_id}/rooms").json()
        ],
        "components": [c["name"] for c in client.get(f"/projects/{project_id}/components").json()],
        "elevations": [e["title"] for e in client.get(f"/projects/{project_id}/elevations").json()],
    }


def test_save_list_and_read_a_version(client, project_id):
    fill(client, project_id)

    response = client.post(f"/projects/{project_id}/versions", json={"label": "Anteproyecto"})

    assert response.status_code == 201
    version = response.json()
    assert version["version_number"] == 1
    assert version["label"] == "Anteproyecto"
    assert version["contents"] == {
        "terrains": 1,
        "plans": 1,
        "rooms": 1,
        "components": 1,
        "materials": 1,
        "elevations": 1,
        "tasks": 0,
        "walkthrough_points": 0,
    }

    second = client.post(f"/projects/{project_id}/versions").json()
    assert second["version_number"] == 2
    assert second["label"] is None

    listed = client.get(f"/projects/{project_id}/versions").json()
    assert [item["version_number"] for item in listed] == [2, 1]
    assert "snapshot" not in listed[0]

    detail = client.get(f"/versions/{version['id']}").json()
    assert detail["snapshot"]["format"] == 1
    assert detail["snapshot"]["project"]["progress"] == 30
    assert detail["snapshot"]["materials"][0]["name"] == "Cemento"


def test_restore_brings_back_the_saved_state(client, project_id):
    fill(client, project_id)
    saved = contents(client, project_id)
    version = client.post(f"/projects/{project_id}/versions").json()

    for material in client.get(f"/projects/{project_id}/materials").json():
        client.delete(f"/materials/{material['id']}")
    for plan in client.get(f"/projects/{project_id}/plans").json():
        client.delete(f"/plans/{plan['id']}")
    client.post(f"/projects/{project_id}/materials", json={"name": "Arena", "unit": "m3"})
    client.patch(f"/projects/{project_id}", json={"progress": 90})

    response = client.post(f"/versions/{version['id']}/restore")

    assert response.status_code == 200
    assert response.json()["progress"] == 30
    assert response.json()["cover_file_id"] is not None
    assert contents(client, project_id) == saved
    assert client.get(f"/projects/{project_id}/undo").json() == []


def test_restore_first_saves_the_current_state(client, project_id):
    fill(client, project_id)
    version = client.post(f"/projects/{project_id}/versions").json()
    client.post(f"/projects/{project_id}/materials", json={"name": "Arena", "unit": "m3"})

    client.post(f"/versions/{version['id']}/restore")

    versions = client.get(f"/projects/{project_id}/versions").json()
    backup = versions[0]
    assert backup["version_number"] == 2
    assert backup["label"] == "Before restoring version 1"
    assert backup["contents"]["materials"] == 2

    client.post(f"/versions/{backup['id']}/restore")
    names = [m["name"] for m in client.get(f"/projects/{project_id}/materials").json()]
    assert sorted(names) == ["Arena", "Cemento"]


def test_restore_drops_links_to_files_that_are_gone(client, project_id):
    file = fill(client, project_id)
    version = client.post(f"/projects/{project_id}/versions").json()
    client.delete(f"/files/{file['id']}")

    project = client.post(f"/versions/{version['id']}/restore").json()

    assert project["cover_file_id"] is None
    assert contents(client, project_id)["plans"] == [("Planta baja", False)]


def test_activity_records_saving_and_restoring(client, project_id):
    version = client.post(f"/projects/{project_id}/versions", json={"label": "V1"}).json()
    client.post(f"/versions/{version['id']}/restore")

    items = client.get(f"/projects/{project_id}/activity").json()["items"]

    assert [item["action"] for item in items] == ["version_restored", "version_saved", "created"]

    backup = client.get(f"/projects/{project_id}/versions").json()[0]
    assert items[0]["detail"]["backup_version_id"] == backup["id"]


def test_versions_need_a_session(client, project_id):
    version = client.post(f"/projects/{project_id}/versions").json()
    anonymous = TestClient(app)

    assert anonymous.get(f"/projects/{project_id}/versions").status_code == 401
    assert anonymous.post(f"/projects/{project_id}/versions").status_code == 401
    assert anonymous.get(f"/versions/{version['id']}").status_code == 401
    assert anonymous.post(f"/versions/{version['id']}/restore").status_code == 401


def test_versions_of_other_users_are_not_found(client, project_id, stranger):
    version = client.post(f"/projects/{project_id}/versions").json()

    assert stranger.get(f"/projects/{project_id}/versions").status_code == 404
    assert stranger.post(f"/projects/{project_id}/versions").status_code == 404
    assert stranger.get(f"/versions/{version['id']}").status_code == 404
    assert stranger.post(f"/versions/{version['id']}/restore").status_code == 404
    assert client.get("/versions/9999").json() == {"detail": "Version not found"}


@pytest.mark.parametrize("label", ["", "x" * 161])
def test_invalid_label_is_rejected(client, project_id, label):
    response = client.post(f"/projects/{project_id}/versions", json={"label": label})

    assert response.status_code == 422


def test_duplicate_copies_the_contents_without_files(client, project_id):
    fill(client, project_id)

    response = client.post(f"/projects/{project_id}/duplicate")

    assert response.status_code == 201
    copy = response.json()
    assert copy["name"] == "Demo House (copia)"
    assert copy["location"] == "Quito"
    assert copy["progress"] == 30
    assert copy["cover_file_id"] is None
    assert copy["status"] == "draft"

    original = contents(client, project_id)
    copied = contents(client, copy["id"])
    assert copied["plans"] == [("Planta baja", False)]
    assert {key: value for key, value in copied.items() if key != "plans"} == {
        key: value for key, value in original.items() if key != "plans"
    }
    assert client.get(f"/projects/{copy['id']}/files").json() == []

    again = client.post(f"/projects/{project_id}/duplicate").json()
    assert again["name"] == "Demo House (copia) (2)"


def test_duplicate_accepts_a_name(client, project_id):
    response = client.post(f"/projects/{project_id}/duplicate", json={"name": "Variante B"})

    assert response.status_code == 201
    assert response.json()["name"] == "Variante B"
    assert (
        client.post(f"/projects/{project_id}/duplicate", json={"name": "Variante B"}).status_code
        == 409
    )
    assert client.post(f"/projects/{project_id}/duplicate", json={"name": ""}).status_code == 422


def test_duplicate_of_an_archived_project_is_a_draft(client, project_id):
    client.post(f"/projects/{project_id}/archive")

    copy = client.post(f"/projects/{project_id}/duplicate").json()

    assert copy["status"] == "draft"
    assert copy["archived_at"] is None


def test_duplicate_is_recorded_and_needs_an_own_project(client, project_id, stranger):
    copy = client.post(f"/projects/{project_id}/duplicate").json()
    items = client.get(f"/projects/{copy['id']}/activity").json()["items"]

    assert items[0]["action"] == "duplicated"
    assert items[0]["detail"]["source_project_id"] == project_id
    assert stranger.post(f"/projects/{project_id}/duplicate").status_code == 404
    assert TestClient(app).post(f"/projects/{project_id}/duplicate").status_code == 401


def test_restore_unlinks_the_spatial_elements_of_replaced_rooms(client, project_id):
    plan = client.post(f"/projects/{project_id}/plans", json={"title": "Planta"}).json()
    room = client.post(
        f"/projects/{project_id}/rooms",
        json={
            "plan_id": plan["id"],
            "name": "Baño",
            "x_m": 0,
            "y_m": 0,
            "width_m": 2,
            "depth_m": 2,
        },
    ).json()
    element = client.post(
        "/api/v1/spatial-data/elements",
        json={
            "project_id": project_id,
            "room_id": room["id"],
            "layer": "installations",
            "kind": "water_pipe",
            "name": "Tubería",
            "min_x_m": 0,
            "min_y_m": 0,
            "min_z_m": 0,
            "max_x_m": 1,
            "max_y_m": 0.1,
            "max_z_m": 0.1,
        },
    ).json()
    version = client.post(f"/projects/{project_id}/versions").json()

    client.post(f"/versions/{version['id']}/restore")

    kept = client.get(f"/api/v1/spatial-data/elements/{element['id']}")
    assert kept.status_code == 200
    assert kept.json()["room_id"] is None
    assert [r["name"] for r in client.get(f"/projects/{project_id}/rooms").json()] == ["Baño"]
