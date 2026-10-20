import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import register


@pytest.fixture
def project_id(client):
    register(client)
    return client.post("/projects", json={"name": "Demo House"}).json()["id"]


def activity(client, project_id, **params):
    response = client.get(f"/projects/{project_id}/activity", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def actions(client, project_id, **params):
    return [
        (item["action"], item["entity_type"], item["detail"].get("label"))
        for item in activity(client, project_id, **params)["items"]
    ]


def test_creating_editing_and_deleting_are_recorded_newest_first(client, project_id):
    terrain = client.post(
        f"/projects/{project_id}/terrains", json={"name": "Lote", "area_m2": 100}
    ).json()
    client.patch(f"/terrains/{terrain['id']}", json={"area_m2": 120, "soil_type": "clay"})
    client.delete(f"/terrains/{terrain['id']}")

    assert actions(client, project_id) == [
        ("deleted", "terrain", "Lote"),
        ("updated", "terrain", "Lote"),
        ("created", "terrain", "Lote"),
        ("created", "project", "Demo House"),
    ]

    updated = activity(client, project_id)["items"][1]
    assert updated["detail"]["fields"] == ["area_m2", "soil_type"]
    assert updated["entity_id"] == terrain["id"]
    assert updated["user_id"] is not None


def test_every_kind_of_element_is_recorded(client, project_id):
    plan = client.post(f"/projects/{project_id}/plans", json={"title": "Planta"}).json()
    client.post(f"/projects/{project_id}/materials", json={"name": "Cemento", "unit": "saco"})
    client.post(
        f"/projects/{project_id}/elevations", json={"title": "Norte", "orientation": "north"}
    )
    room = {"plan_id": plan["id"], "name": "Sala", "x_m": 0, "y_m": 0, "width_m": 4, "depth_m": 4}
    client.post(f"/projects/{project_id}/rooms", json=room)
    client.post(
        f"/projects/{project_id}/components",
        json={**room, "name": "C1", "kind": "column", "height_m": 3},
    )
    client.post(
        f"/projects/{project_id}/recommendations",
        json={"category": "Estructura", "content": "Revisar"},
    )
    client.post(
        f"/projects/{project_id}/files",
        files={"file": ("a.png", b"\x89PNG\r\n\x1a\nimage", "image/png")},
    )
    client.patch(f"/projects/{project_id}", json={"description": "Casa"})

    recorded = {entity for _, entity, _ in actions(client, project_id)}

    assert recorded == {
        "project",
        "plan",
        "material",
        "elevation",
        "room",
        "component",
        "recommendation",
        "file",
    }


def test_undo_and_redo_are_recorded(client, project_id):
    material = client.post(
        f"/projects/{project_id}/materials", json={"name": "Cemento", "unit": "saco"}
    ).json()
    client.delete(f"/materials/{material['id']}")
    client.post(f"/projects/{project_id}/undo")
    client.post(f"/projects/{project_id}/redo")

    assert [action for action, _, _ in actions(client, project_id)][:3] == [
        "deleted",
        "restored",
        "deleted",
    ]


def test_activity_is_paginated_and_filtered(client, project_id):
    for number in range(5):
        client.post(f"/projects/{project_id}/plans", json={"title": f"Plan {number}"})

    page = activity(client, project_id, page=2, page_size=2, entity_type="plan")

    assert page["total"] == 5
    assert page["page"] == 2
    assert [item["detail"]["label"] for item in page["items"]] == ["Plan 2", "Plan 1"]


@pytest.mark.parametrize("params", [{"page": 0}, {"page_size": 101}, {"entity_type": "x" * 41}])
def test_invalid_parameters_are_rejected(client, project_id, params):
    response = client.get(f"/projects/{project_id}/activity", params=params)

    assert response.status_code == 422


def test_activity_needs_a_session_and_an_own_project(client, project_id):
    assert TestClient(app).get(f"/projects/{project_id}/activity").status_code == 401

    other = TestClient(app)
    register(other, name="Eve", email="eve@example.com")

    response = other.get(f"/projects/{project_id}/activity")

    assert response.status_code == 404
    assert response.json() == {"detail": "Project not found"}


def test_deleting_the_project_removes_its_activity(client, project_id):
    client.post(f"/projects/{project_id}/plans", json={"title": "Planta"})
    client.delete(f"/projects/{project_id}")

    again = client.post("/projects", json={"name": "Demo House"}).json()["id"]

    assert actions(client, again) == [("created", "project", "Demo House")]
