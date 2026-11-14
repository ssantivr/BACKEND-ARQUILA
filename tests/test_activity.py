from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.main import app
from app.repositories.material_repository import MaterialRepository
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
    items = activity(client, project_id)["items"]
    # A redo is told apart from a deletion made by hand.
    assert items[0]["detail"].get("via") == "redo"
    assert items[2]["detail"].get("via") is None


SQUARE = {"x_m": 0, "y_m": 0, "width_m": 4, "depth_m": 4}


def test_roof_and_surface_changes_are_recorded_with_their_values(client, project_id):
    plan = client.post(f"/projects/{project_id}/plans", json={"title": "Planta"}).json()
    room = client.post(
        f"/projects/{project_id}/rooms",
        json={"plan_id": plan["id"], "name": "Sala", **SQUARE},
    ).json()

    client.patch(f"/projects/{project_id}/structure/roof", json={"roof": "flat"})
    client.patch(
        f"/projects/{project_id}/structure/room/{room['id']}/surface", json={"surface": "brick"}
    )

    surface, roof = activity(client, project_id)["items"][:2]
    assert (surface["entity_type"], surface["detail"]["label"]) == ("room", "Sala")
    assert (surface["old_value"], surface["new_value"]) == ({"surface": None}, {"surface": "brick"})
    assert (roof["entity_type"], roof["detail"]["fields"]) == ("project", ["roof"])
    assert roof["new_value"] == {"roof": "flat"}


def test_a_room_edited_through_the_v1_api_is_recorded(client, project_id):
    plan = client.post(f"/projects/{project_id}/plans", json={"title": "Planta"}).json()
    room = client.post(
        f"/projects/{project_id}/rooms",
        json={"plan_id": plan["id"], "name": "Sala", **SQUARE},
    ).json()

    edited = client.patch(f"/api/v1/rooms/{room['id']}", json={"category": "kitchen"})
    assert edited.status_code == 200

    updated = activity(client, project_id)["items"][0]
    assert (updated["action"], updated["entity_type"]) == ("updated", "room")
    assert updated["new_value"] == {"category": "kitchen"}


def test_a_project_made_from_a_template_is_recorded(client):
    register(client)
    project = client.post("/templates/vivienda-compacta/projects").json()

    created = activity(client, project["id"])["items"][-1]
    assert (created["action"], created["entity_type"]) == ("created", "project")
    assert created["detail"]["template_id"] == "vivienda-compacta"


def test_an_upload_and_its_entry_are_saved_together(client, project_id):
    png = bytes([0x89]) + b"PNG" + bytes([13, 10, 26, 10]) + b"fake image data"
    file = client.post(
        f"/projects/{project_id}/files", files={"file": ("plan.png", png, "image/png")}
    ).json()

    created = activity(client, project_id)["items"][0]
    assert (created["action"], created["entity_type"], created["entity_id"]) == (
        "created",
        "file",
        file["id"],
    )


def test_a_change_that_fails_leaves_no_entry(client, project_id):
    material = {"name": "Cemento", "unit": "saco"}
    client.post(f"/projects/{project_id}/materials", json=material)
    before = activity(client, project_id)["total"]

    # The name is taken, so the second material is refused and nothing is recorded.
    response = client.post(f"/projects/{project_id}/materials", json=material)

    assert response.status_code == 409
    assert activity(client, project_id)["total"] == before


def test_an_entry_already_flushed_is_rolled_back_when_the_save_fails(
    client, project_id, monkeypatch
):
    material = client.post(
        f"/projects/{project_id}/materials", json={"name": "Cemento", "unit": "saco"}
    ).json()
    before = activity(client, project_id)["total"]

    def failing_save(self, entity):
        # The entry is in the transaction by now; the commit never comes.
        self.session.flush()
        raise IntegrityError("UPDATE materials", {}, Exception("forced"))

    monkeypatch.setattr(MaterialRepository, "save", failing_save)
    response = client.patch(f"/materials/{material['id']}", json={"unit": "bulto"})
    monkeypatch.undo()

    assert response.status_code == 409
    assert activity(client, project_id)["total"] == before
    assert client.get(f"/materials/{material['id']}").json()["unit"] == "saco"


def test_an_update_that_changes_nothing_records_nothing(client, project_id):
    terrain = client.post(
        f"/projects/{project_id}/terrains", json={"name": "Lote", "area_m2": 100}
    ).json()
    before = activity(client, project_id)["total"]

    response = client.patch(f"/terrains/{terrain['id']}", json={"name": "Lote", "area_m2": 100})

    assert response.status_code == 200
    assert activity(client, project_id)["total"] == before


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


def test_an_update_records_who_where_and_the_values_before_and_after(client, project_id):
    terrain = client.post(
        f"/projects/{project_id}/terrains", json={"name": "Lote", "area_m2": 100}
    ).json()
    client.patch(
        f"/terrains/{terrain['id']}",
        json={"area_m2": 120, "name": "Lote"},
        headers={"X-Arquila-Module": "terrain"},
    )

    updated = activity(client, project_id)["items"][0]

    assert updated["action"] == "updated"
    assert updated["origin"] == "user"
    assert updated["source_module"] == "terrain"
    # Only the field that really changed: the name was sent with the same value.
    assert updated["detail"]["fields"] == ["area_m2"]
    assert updated["old_value"] == {"area_m2": 100}
    assert updated["new_value"] == {"area_m2": 120}


def test_a_creation_has_no_values_and_an_unknown_module_is_not_stored(client, project_id):
    client.post(
        f"/projects/{project_id}/plans",
        json={"title": "Planta"},
        headers={"X-Arquila-Module": "<script>"},
    )

    created = activity(client, project_id)["items"][0]

    assert created["action"] == "created"
    assert created["source_module"] is None
    assert created["old_value"] is None
    assert created["new_value"] is None


def test_the_time_of_an_entry_is_sent_in_utc_with_its_offset(client, project_id):
    created_at = activity(client, project_id)["items"][0]["created_at"]

    assert created_at.endswith(("Z", "+00:00")), created_at
    # The instant itself, not only the suffix: a naive local time labelled UTC would be off by
    # the server's offset (five hours in America/Bogota).
    sent = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    assert abs(datetime.now(UTC) - sent) < timedelta(minutes=2), created_at


def test_the_module_of_one_request_does_not_leak_into_the_next(client, project_id):
    client.post(
        f"/projects/{project_id}/plans", json={"title": "A"}, headers={"X-Arquila-Module": "viewer"}
    )
    client.post(f"/projects/{project_id}/plans", json={"title": "B"})

    newest, previous = activity(client, project_id)["items"][:2]

    assert (newest["detail"]["label"], newest["source_module"]) == ("B", None)
    assert (previous["detail"]["label"], previous["source_module"]) == ("A", "viewer")


def test_moving_a_room_in_the_3d_viewer_records_its_old_and_new_position(client, project_id):
    plan = client.post(f"/projects/{project_id}/plans", json={"title": "Planta"}).json()
    room = client.post(
        f"/projects/{project_id}/rooms",
        json={
            "plan_id": plan["id"],
            "name": "Sala",
            "x_m": 0,
            "y_m": 0,
            "width_m": 4,
            "depth_m": 4,
        },
    ).json()

    response = client.patch(
        f"/rooms/{room['id']}",
        json={"x_m": 2.5, "y_m": 0, "width_m": 4.5, "depth_m": 4, "height_m": room["height_m"]},
        headers={"X-Arquila-Module": "viewer"},
    )
    assert response.status_code == 200, response.text

    moved = activity(client, project_id)["items"][0]

    assert (moved["action"], moved["entity_type"], moved["source_module"]) == (
        "updated",
        "room",
        "viewer",
    )
    assert moved["old_value"] == {"x_m": 0, "width_m": 4}
    assert moved["new_value"] == {"x_m": 2.5, "width_m": 4.5}
